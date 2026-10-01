"""Music coordinates are explicit authoring data, verified with synthetic PCM."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

try:
    import matter_audio_core
except ModuleNotFoundError as exc:
    if exc.name != "matter_audio_core":
        raise
    raise unittest.SkipTest("Install the optional audio dependency for music annotation tests") from exc

from matter_audio_core.artifacts import ArtifactStore
from matter_audio_core.contracts import canonical, digest, fingerprint
from matter_audio_core.errors import AudioError
from matter_audio_core.media import PCM, decode_wav, encode_wav, sample_bytes
from matter_audio_core.sessions import SessionService
from score_matter.cli import main
from score_matter.music import annotate, execute, plan, resolve_position, show


def fixed(*, bpm="120", numerator=1, denominator=4, beats=4, unit=4, origin=0):
    return {"mode": "fixed", "bpm": bpm,
            "bpm_unit": {"numerator": numerator, "denominator": denominator},
            "meter": {"beats": beats, "unit": unit}, "origin_frame": origin}


def region(identifier="phrase", start=None, end=None):
    return {"id": identifier, "start": {"frame": 100} if start is None else start,
            "end": {"frame": 500} if end is None else end}


class MusicCoordinateTests(unittest.TestCase):
    media = {"sample_rate_hz": 8000, "frame_count": 20000000}

    def test_four_four_uses_meter_beats_and_one_based_coordinates(self):
        timing = fixed()
        for point, expected in [({"bar": 1, "beat": "1"}, 0),
                                ({"bar": 1, "beat": "2.5"}, 6000),
                                ({"bar": 2, "beat": "1"}, 16000),
                                ({"bar": 3, "beat": "1"}, 32000)]:
            with self.subTest(point=point):
                result = resolve_position(point, timing, self.media)
                self.assertEqual(result["frame"], expected)
                self.assertEqual(result["error_frames"], "0")

    def test_six_eight_does_not_infer_the_bpm_note_unit(self):
        point = {"bar": 2, "beat": "1"}
        # At 60 dotted quarters/minute a 6/8 bar is 2 s; at 60 eighths it is 6 s.
        dotted = fixed(bpm="60", numerator=3, denominator=8, beats=6, unit=8)
        eighth = fixed(bpm="60", denominator=8, beats=6, unit=8)
        quarter = fixed(bpm="60", beats=6, unit=8)
        self.assertEqual(resolve_position(point, dotted, self.media)["frame"], 16000)
        self.assertEqual(resolve_position(point, eighth, self.media)["frame"], 48000)
        self.assertEqual(resolve_position(point, quarter, self.media)["frame"], 24000)
        self.assertEqual(resolve_position({"bar": 1, "beat": "4"}, dotted, self.media)["frame"], 8000)

    def test_origin_and_half_frame_rounding_are_absolute_half_up(self):
        point = {"bar": 1, "beat": "2"}
        result = resolve_position(point, fixed(bpm="512", origin=1), self.media)
        self.assertEqual(result, {"frame": 939, "exact_frame": "1877/2",
                                  "error_frames": "1/2", "error_seconds": "1/16000"})
        self.assertEqual(resolve_position({"bar": 1, "beat": "1"}, fixed(origin=123), self.media)["frame"], 123)
        for seconds, frame in [("0.0000625", 1), ("0.0001875", 2)]:
            result = resolve_position({"seconds": seconds}, {"mode": "free"}, self.media)
            self.assertEqual(result["frame"], frame)
            self.assertEqual(result["error_frames"], "1/2")

    def test_distant_position_does_not_accumulate_rounded_beat_lengths(self):
        result = resolve_position({"bar": 1001, "beat": "1"}, fixed(bpm="137"), self.media)
        # 4000 quarter notes * 60 * 8000 / 137, rounded once, not 4000 * 3504.
        self.assertEqual(result["exact_frame"], "1920000000/137")
        self.assertEqual(result["frame"], 14014599)
        self.assertEqual(result["error_frames"], "63/137")
        self.assertNotEqual(result["frame"], 4000 * 3504)

    def test_free_and_unknown_accept_frames_and_seconds_without_guessing_grid(self):
        for mode in ("free", "unknown"):
            with self.subTest(mode=mode):
                self.assertEqual(resolve_position({"frame": 987}, {"mode": mode}, self.media)["frame"], 987)
                self.assertEqual(resolve_position({"seconds": "1.25"}, {"mode": mode}, self.media)["frame"], 10000)
                with self.assertRaises(AudioError):
                    resolve_position({"bar": 1, "beat": "1"}, {"mode": mode}, self.media)


class MusicAnnotationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = self.root / "workspace"
        self.store = ArtifactStore(self.workspace, product="score-matter")
        self.source = self.root / "synthetic.wav"
        self.pcm = PCM(sample_bytes(array("h", [i % 2001 - 1000 for i in range(40000)])), 8000, 1)
        self.source.write_bytes(encode_wav(self.pcm))
        self.audio = self.store.import_wav(self.source, "source")["outputs"][0]
        self.sessions = SessionService(self.store)
        runtime = patch.dict("os.environ", {"SCORE_MATTER_SA3_ROOT": str(self.root / "absent-runtime")})
        runtime.start()
        self.addCleanup(runtime.stop)
        for name in ("score_matter.authoring.subprocess.run", "score_matter.sa3_edit.run_process"):
            mocked = patch(name, side_effect=AssertionError("Music annotation must never launch a model"))
            backend = mocked.start()
            self.addCleanup(mocked.stop)
            self.addCleanup(backend.assert_not_called)

    def annotation_request(self, request_id="annotation", **changes):
        return {"schema": "score-music-annotate/v1", "request_id": request_id,
                "asset_id": self.audio["asset_id"], "source": "agent", "timing": fixed(),
                "regions": [region()], **changes}

    def annotation(self, **changes):
        return annotate(self.store, self.annotation_request(**changes))

    def plan_request(self, annotation, request_id="plan", target=None, **changes):
        return {"schema": "score-music-plan/v1", "request_id": request_id,
                "annotation_id": annotation["outputs"][0]["asset_id"], "region_ids": ["phrase"],
                "target": {"kind": "trim"} if target is None else target, **changes}

    def prepare(self, annotation=None, **changes):
        return plan(self.store, self.plan_request(annotation or self.annotation(), **changes))

    def call(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["audio", "--workspace", str(self.workspace), *map(str, arguments), "--json"])
        return code, json.loads(output.getvalue())

    def cli_request(self, command, body):
        path = self.root / "request.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return self.call("music", command, "--request", path)

    def create_session(self):
        return self.sessions.mutate("create", {"schema": "matter-session-create/v1", "request_id": "create",
            "session_id": "music", "name": "Synthetic music fixture", "asset_id": self.audio["asset_id"]})

    def locks(self, ranges, *, revision=1, request_id="locks"):
        return self.sessions.mutate("constraints", {"schema": "matter-constraints-set/v1", "request_id": request_id,
            "session_id": "music", "expected_revision": revision,
            "regions": [{"start_frame": start, "end_frame": end} for start, end in ranges]})

    def groups(self):
        return len(list((self.workspace / "objects").iterdir()))

    def test_cli_discovers_and_preserves_immutable_annotation_with_exact_audio_binding(self):
        code, capability = self.call("capabilities")
        self.assertEqual(code, 0)
        self.assertIn("score-music-annotate/v1", json.dumps(capability["product_capabilities"]))
        before = self.source.read_bytes()
        request = self.annotation_request()
        code, result = self.cli_request("annotate", request)
        self.assertEqual(code, 0)
        self.assertEqual(result["audio_model_calls"], 0)
        self.assertEqual(len(result["outputs"]), 1)
        annotation_id = result["outputs"][0]["asset_id"]
        code, saved = self.call("music", "show", annotation_id)
        self.assertEqual(code, 0)
        self.assertEqual(saved["document"]["audio"]["asset_id"], self.audio["asset_id"])
        self.assertEqual(saved["document"]["audio"]["digest"], digest(before))
        self.assertEqual(saved["document"]["request"]["source"], "agent")
        self.assertEqual(self.cli_request("annotate", request), (0, result))
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse((self.workspace / "sessions.sqlite3").exists())

    def test_annotation_request_ids_replay_or_conflict_without_mutating_saved_document(self):
        first = self.annotation()
        saved = show(self.store, first["outputs"][0]["asset_id"])
        self.assertEqual(self.annotation(), first)
        with self.assertRaises(AudioError) as caught:
            self.annotation(source="user")
        self.assertEqual(caught.exception.code, "request_conflict")
        self.assertEqual(show(self.store, first["outputs"][0]["asset_id"]), saved)

    def test_invalid_grid_coordinates_ranges_and_tempo_maps_fail_before_publication(self):
        cases = [
            {"timing": {**fixed(), "tempo_map": []}},
            {"timing": {**fixed(), "mode": "variable"}},
            {"timing": {**fixed(), "bpm": "0"}},
            {"timing": {**fixed(), "bpm": "1001"}},
            {"timing": {**fixed(), "bpm_unit": {"numerator": 1, "denominator": 3}}},
            {"timing": {**fixed(), "origin_frame": -1}},
            {"regions": [region(start={"bar": 0, "beat": "1"})]},
            {"regions": [region(start={"bar": 1, "beat": "0"})]},
            {"regions": [region(start={"bar": 1, "beat": "5"})]},
            {"regions": [region(start={"frame": True})]},
            {"regions": [region(start={"frame": -1})]},
            {"regions": [region(start={"seconds": "NaN"})]},
            {"regions": [region(start={"seconds": "-0.1"})]},
            {"regions": [region(start={"frame": 100, "seconds": "1"})]},
            {"regions": [region(start={"frame": 500}, end={"frame": 100})]},
            {"regions": [region(end={"frame": 40001})]},
            {"regions": [region(start={"seconds": "0.00001"}, end={"seconds": "0.00002"})]},
            {"regions": [region(), region()]},
            {"timing": {"mode": "free"}, "regions": [region(start={"bar": 1, "beat": "1"})]},
        ]
        before = self.groups()
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(AudioError):
                self.annotation(**changes)
            self.assertEqual(self.groups(), before)

    def test_unknown_and_free_annotations_use_explicit_frame_or_second_ranges(self):
        for mode in ("unknown", "free"):
            result = self.annotation(request_id=mode, timing={"mode": mode},
                                     regions=[region(start={"frame": 0}, end={"seconds": "1.25"})])
            prepared = self.prepare(result, request_id="plan-" + mode)
            output = execute(self.store, prepared["outputs"][0]["asset_id"])["outputs"][0]
            self.assertEqual(output["media"]["frame_count"], 10000)

    def test_note_units_reject_float_and_boolean_values_before_publication(self):
        before = self.groups()
        for field, value in [("meter", 4.0), ("bpm_unit", 4.0), ("bpm_unit", True)]:
            timing = fixed()
            timing[field]["unit" if field == "meter" else "denominator"] = value
            with self.subTest(field=field, value=value), self.assertRaises(AudioError) as caught:
                self.annotation(timing=timing)
            self.assertEqual(caught.exception.code, "invalid_request")
            self.assertEqual(self.groups(), before)

    def test_wrong_asset_types_and_modified_annotation_digest_are_rejected(self):
        first = self.annotation()
        with self.assertRaises(AudioError):
            self.annotation(request_id="metadata-not-audio", asset_id=first["outputs"][0]["asset_id"])
        code, missing = self.cli_request("annotate", self.annotation_request(
            request_id="missing-audio", asset_id="a_" + "0" * 32 + "_0"))
        self.assertEqual(code, 2)
        self.assertEqual(missing["error"]["code"], "io_or_integrity_error")
        metadata = first["outputs"][0]
        (self.workspace / metadata["locator"]).write_bytes(b"{}")
        with self.assertRaises(AudioError) as caught:
            self.prepare(first)
        self.assertEqual(caught.exception.code, "integrity_error")

    def test_saved_annotation_cannot_substitute_another_audio_id_or_digest(self):
        annotation = self.annotation()
        original = show(self.store, annotation["outputs"][0]["asset_id"])["document"]
        for index, (field, value) in enumerate([
            ("asset_id", "a_" + "0" * 32 + "_0"),
            ("digest", {"algorithm": "sha256", "hex": "0" * 64}),
        ]):
            document = copy.deepcopy(original)
            document["audio"][field] = value

            def publish(publication):
                publication.add(canonical(document), {"kind": "music_annotation", "content_type": "application/json"},
                                role="music_annotation")
                return {}

            forged = self.store.transact("wrong-binding-" + str(index), {"fixture": index}, publish)
            with self.subTest(field=field), self.assertRaises(AudioError) as caught:
                show(self.store, forged["outputs"][0]["asset_id"])
            self.assertEqual(caught.exception.code, "music_binding_mismatch")

    def test_trim_plan_is_preview_then_exact_pcm_execution_with_no_automatic_annotation_transfer(self):
        annotation = self.annotation()
        before = self.groups()
        code, prepared = self.cli_request("plan", self.plan_request(annotation))
        self.assertEqual(code, 0)
        self.assertEqual(self.groups(), before + 1)
        self.assertEqual(len(prepared["outputs"]), 1)
        self.assertNotEqual(prepared["outputs"][0]["media"].get("codec"), "pcm_s16le")
        self.assertFalse((self.workspace / "sessions.sqlite3").exists())
        plan_id = prepared["outputs"][0]["asset_id"]
        code, result = self.call("music", "execute", plan_id)
        self.assertEqual(code, 0)
        self.assertEqual(result["audio_model_calls"], 0)
        output = result["outputs"][0]
        self.assertEqual(decode_wav(self.store.asset(output["asset_id"])[1]).payload, self.pcm.payload[200:1000])
        self.assertEqual(output["media"]["frame_count"], 400)
        self.assertEqual(self.call("music", "execute", plan_id), (0, result))
        with self.assertRaises(AudioError):
            show(self.store, output["asset_id"])
        self.assertEqual(show(self.store, annotation["outputs"][0]["asset_id"])["document"]["audio"]["asset_id"], self.audio["asset_id"])

    def test_plan_request_conflicts_and_different_annotations_bind_different_core_requests(self):
        first = self.annotation()
        original = self.prepare(first)
        self.assertEqual(self.prepare(first), original)
        with self.assertRaises(AudioError) as caught:
            self.prepare(first, target={"kind": "loop", "crossfade_frames": 0})
        self.assertEqual(caught.exception.code, "request_conflict")
        second = self.annotation(request_id="annotation-2", source="project")
        other = self.prepare(second, request_id="plan-2")
        one = show(self.store, original["outputs"][0]["asset_id"])["document"]["core_request"]
        two = show(self.store, other["outputs"][0]["asset_id"])["document"]["core_request"]
        self.assertNotEqual(one["request_id"], two["request_id"])

    def test_plan_requires_existing_unique_regions_and_one_range_for_audio_operations(self):
        annotation = self.annotation(regions=[region(), region("second", {"frame": 600}, {"frame": 700})])
        before = self.groups()
        for identifiers in (["absent"], ["phrase", "phrase"], ["phrase", "second"]):
            with self.subTest(identifiers=identifiers), self.assertRaises(AudioError):
                self.prepare(annotation, region_ids=identifiers)
            self.assertEqual(self.groups(), before)
        with self.assertRaises(AudioError) as caught:
            self.prepare(annotation, target={"kind": "score.sa3_inpaint/v1", "prompt": "Do not run"})
        self.assertEqual(caught.exception.code, "invalid_request")
        self.assertEqual(self.groups(), before)

    def test_unfinished_plan_and_execution_claims_stay_pending_without_new_ids(self):
        annotation = self.annotation()
        publication = self.store._publish

        def interrupt_result(target, files):
            if target.parent.name == "objects":
                raise OSError("Synthetic interrupted music publication")
            return publication(target, files)

        with patch.object(self.store, "_publish", side_effect=interrupt_result), self.assertRaises(OSError):
            self.prepare(annotation, request_id="pending-plan")
        claims = len(list((self.workspace / "requests").iterdir()))
        with self.assertRaises(AudioError) as caught:
            self.prepare(annotation, request_id="pending-plan")
        self.assertEqual(caught.exception.code, "recovery_pending")
        self.assertEqual(len(list((self.workspace / "requests").iterdir())), claims)

        prepared = self.prepare(annotation, request_id="executable-plan")
        plan_id = prepared["outputs"][0]["asset_id"]
        groups = self.groups()
        with patch.object(self.store, "_publish", side_effect=interrupt_result), self.assertRaises(OSError):
            execute(self.store, plan_id)
        claims = len(list((self.workspace / "requests").iterdir()))
        with self.assertRaises(AudioError) as caught:
            execute(self.store, plan_id)
        self.assertEqual(caught.exception.code, "recovery_pending")
        self.assertEqual(len(list((self.workspace / "requests").iterdir())), claims)
        self.assertEqual(self.groups(), groups)

    def test_loop_overlap_shortens_output_period_and_zero_overlap_preserves_slice(self):
        annotation = self.annotation(regions=[region(start={"bar": 1, "beat": "1"}, end={"bar": 2, "beat": "1"})])
        for overlap in (0, 64):
            prepared = self.prepare(annotation, request_id="loop-" + str(overlap),
                                    target={"kind": "loop", "crossfade_frames": overlap})
            period = show(self.store, prepared["outputs"][0]["asset_id"])["document"]["loop"]
            self.assertEqual(period["period_frames"], 16000 - overlap)
            self.assertEqual(period["source_window_frames"], 16000)
            self.assertEqual(period["removed_frames"], overlap)
            result = execute(self.store, prepared["outputs"][0]["asset_id"])
            output = result["outputs"][0]
            self.assertEqual(output["media"]["frame_count"], 16000 - overlap)
            pcm = decode_wav(self.store.asset(output["asset_id"])[1])
            if not overlap:
                self.assertEqual(pcm.payload, self.pcm.payload[:32000])
            else:
                self.assertEqual(pcm.payload[:-overlap * 2], self.pcm.payload[overlap * 2:(16000 - overlap) * 2])
            self.assertEqual(result["findings"][0]["loop"]["end_frame"], 16000 - overlap)
        for overlap in (1, 8001):
            with self.subTest(overlap=overlap), self.assertRaises(AudioError):
                self.prepare(annotation, request_id="bad-loop-" + str(overlap),
                             target={"kind": "loop", "crossfade_frames": overlap})

    def test_constraints_add_union_without_dropping_existing_locks_or_changing_selection(self):
        self.create_session()
        self.locks([(0, 100), (400, 500)])
        annotation = self.annotation(regions=[region("join", {"frame": 100}, {"frame": 450})])
        prepared = self.prepare(annotation, region_ids=["join"],
            target={"kind": "constraints", "session_id": "music", "expected_revision": 2})
        self.assertEqual(self.sessions.show("music")["current"]["revision"], 2)
        result = execute(self.store, prepared["outputs"][0]["asset_id"])
        current = self.sessions.show("music")
        self.assertEqual(current["current"]["selected_asset"]["asset_id"], self.audio["asset_id"])
        self.assertEqual([(r["start_frame"], r["end_frame"]) for r in current["protected_regions"]], [(0, 500)])
        self.locks([(0, 500), (600, 700)], revision=3, request_id="later-locks")
        self.assertEqual(execute(self.store, prepared["outputs"][0]["asset_id"]), result)
        self.assertEqual(self.sessions.show("music")["current"]["revision"], 4)

    def test_constraints_union_refuses_seventeen_disjoint_locks_without_discarding_old_ones(self):
        self.create_session()
        existing = [(i * 20, i * 20 + 10) for i in range(16)]
        self.locks(existing)
        annotation = self.annotation(regions=[region(start={"frame": 1000}, end={"frame": 1100})])
        with self.assertRaises(AudioError) as caught:
            self.prepare(annotation, target={"kind": "constraints", "session_id": "music", "expected_revision": 2})
        self.assertEqual(caught.exception.code, "music_constraint_limit")
        current = self.sessions.show("music")
        self.assertEqual(current["current"]["revision"], 2)
        self.assertEqual([(r["start_frame"], r["end_frame"]) for r in current["protected_regions"]], existing)

    def test_forged_constraint_plan_cannot_omit_historical_existing_locks(self):
        self.create_session()
        self.locks([(0, 50)])
        prepared = self.prepare(target={"kind": "constraints", "session_id": "music", "expected_revision": 2})
        document = copy.deepcopy(show(self.store, prepared["outputs"][0]["asset_id"])["document"])
        document["existing_regions"] = []
        document["core_request"]["regions"] = [{"start_frame": 100, "end_frame": 500}]

        def publish(publication):
            publication.add(canonical(document), {"kind": "music_plan", "content_type": "application/json"}, role="music_plan")
            return {}

        forged = self.store.transact("forged-plan", {"fixture": "missing-old-lock"}, publish)
        with self.assertRaises(AudioError) as caught:
            execute(self.store, forged["outputs"][0]["asset_id"])
        self.assertEqual(caught.exception.code, "music_binding_mismatch")
        current = self.sessions.show("music")
        self.assertEqual(current["current"]["revision"], 2)
        self.assertEqual([(r["start_frame"], r["end_frame"]) for r in current["protected_regions"]], [(0, 50)])

    def test_forged_constraint_plan_cannot_target_another_historical_selected_asset(self):
        self.create_session()
        self.locks([(0, 50)])
        other = self.store.import_wav(self.source, "other-audio")["outputs"][0]
        self.assertEqual(other["digest"], self.audio["digest"])
        self.assertNotEqual(other["asset_id"], self.audio["asset_id"])
        self.sessions.mutate("create", {"schema": "matter-session-create/v1", "request_id": "create-other",
            "session_id": "other", "name": "Identical PCM, distinct asset", "asset_id": other["asset_id"]})
        self.sessions.mutate("constraints", {"schema": "matter-constraints-set/v1", "request_id": "lock-other",
            "session_id": "other", "expected_revision": 1, "regions": [{"start_frame": 0, "end_frame": 50}]})
        annotation = self.annotation(asset_id=other["asset_id"])
        prepared = self.prepare(annotation,
            target={"kind": "constraints", "session_id": "other", "expected_revision": 2})
        document = copy.deepcopy(show(self.store, prepared["outputs"][0]["asset_id"])["document"])
        # Preserve B's valid annotation and coordinates, but retarget the plan to
        # A's historical session with identical old locks and a valid derived ID.
        document["request"]["target"]["session_id"] = "music"
        document["core_request"]["session_id"] = "music"
        binding = {"operation": "score.music.plan/v1", "request": document["request"],
                   "annotation": document["annotation"], "audio": document["audio"]}
        document["core_request"]["request_id"] = "music-" + fingerprint(binding)["hex"]
        self.assertEqual(document["existing_regions"], [{"start_frame": 0, "end_frame": 50}])

        def publish(publication):
            publication.add(canonical(document), {"kind": "music_plan", "content_type": "application/json"}, role="music_plan")
            return {}

        forged = self.store.transact("forged-session-plan", {"fixture": "wrong-historical-asset"}, publish)
        plan_id = forged["outputs"][0]["asset_id"]
        before = {name: self.sessions.show(name) for name in ("music", "other")}
        for operation in (show, execute):
            with self.subTest(operation=operation.__name__), self.assertRaises(AudioError) as caught:
                operation(self.store, plan_id)
            self.assertEqual(caught.exception.code, "music_session_asset_mismatch")
            self.assertEqual({name: self.sessions.show(name) for name in before}, before)
        with self.assertRaises(AudioError) as caught:
            self.sessions.request_status(document["core_request"]["request_id"])
        self.assertEqual(caught.exception.code, "request_not_found")

    def test_constraints_plan_rejects_stale_revision_and_wrong_selected_asset(self):
        self.create_session()
        annotation = self.annotation()
        prepared = self.prepare(annotation,
            target={"kind": "constraints", "session_id": "music", "expected_revision": 1})
        self.locks([(0, 50)])
        with self.assertRaises(AudioError) as caught:
            execute(self.store, prepared["outputs"][0]["asset_id"])
        self.assertEqual(caught.exception.code, "revision_conflict")
        with self.assertRaises(AudioError):
            self.prepare(annotation, request_id="stale-plan",
                target={"kind": "constraints", "session_id": "music", "expected_revision": 1})
        # Equal audio bytes with a distinct asset ID still need their own annotation.
        other = self.store.import_wav(self.source, "new-version")["outputs"][0]
        self.sessions.mutate("create", {"schema": "matter-session-create/v1", "request_id": "other-session",
            "session_id": "other", "name": "Other version", "asset_id": other["asset_id"]})
        with self.assertRaises(AudioError):
            self.prepare(annotation, request_id="wrong-version",
                target={"kind": "constraints", "session_id": "other", "expected_revision": 1})

    def test_protected_trim_rejects_removed_region_and_changed_policy_but_replays_completed_action(self):
        self.create_session()
        self.locks([(200, 300)])
        annotation = self.annotation()
        target = {"kind": "trim", "protection": {"session_id": "music", "revision": 2}}
        prepared = self.prepare(annotation, target=target)
        waiting = self.prepare(annotation, request_id="waiting", target=target)
        finished = execute(self.store, prepared["outputs"][0]["asset_id"])
        self.assertEqual(finished["findings"][0]["protection"]["status"], "verified")
        outside = self.annotation(request_id="outside", regions=[region(start={"frame": 400}, end={"frame": 600})])
        with self.assertRaises(AudioError) as caught:
            self.prepare(outside, request_id="remove-lock", target=target)
        self.assertEqual(caught.exception.code, "constraint_violation")
        self.locks([(200, 300), (350, 400)], revision=2, request_id="changed-policy")
        count = self.groups()
        with self.assertRaises(AudioError) as caught:
            execute(self.store, waiting["outputs"][0]["asset_id"])
        self.assertEqual(caught.exception.code, "constraint_conflict")
        self.assertEqual(self.groups(), count)
        self.assertEqual(execute(self.store, prepared["outputs"][0]["asset_id"]), finished)
        self.assertEqual(self.sessions.show("music")["current"]["selected_asset"]["asset_id"], self.audio["asset_id"])

    def test_loop_planning_rejects_locks_in_removed_head_and_blended_tail(self):
        self.create_session()
        annotation = self.annotation()
        revision = 1
        for start, end in [(100, 120), (450, 460)]:
            self.locks([(start, end)], revision=revision, request_id="lock-" + str(start))
            revision += 1
            with self.subTest(start=start), self.assertRaises(AudioError) as caught:
                self.prepare(annotation, request_id="protected-loop-" + str(start),
                    target={"kind": "loop", "crossfade_frames": 64,
                            "protection": {"session_id": "music", "revision": revision}})
            self.assertEqual(caught.exception.code, "constraint_violation")


if __name__ == "__main__":
    unittest.main()
