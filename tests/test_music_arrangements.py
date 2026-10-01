"""Ordered musical sections compile to explicit, immutable PCM arrangements."""
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
    raise unittest.SkipTest("Install the optional audio dependency for music arrangement tests") from exc

from matter_audio_core.artifacts import ArtifactStore
from matter_audio_core.contracts import canonical
from matter_audio_core.errors import AudioError
from matter_audio_core.media import PCM, decode_wav, encode_wav, sample_bytes
from matter_audio_core.sessions import SessionService
from score_matter.cli import main
from score_matter.music import annotate, arrange, execute, show


def grid(bpm, numerator, denominator, beats, unit, origin):
    return {"mode": "fixed", "bpm": bpm, "bpm_unit": {"numerator": numerator, "denominator": denominator},
            "meter": {"beats": beats, "unit": unit}, "origin_frame": origin}


class MusicArrangementTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store = ArtifactStore(self.root / "workspace", product="score-matter")
        self.sessions = SessionService(self.store)
        self.a, self.a_path, self.a_pcm = self.source("a")
        self.b, self.b_path, self.b_pcm = self.source("b", bias=2000)
        self.a_timing = grid("120", 1, 4, 4, 4, 10)
        self.b_timing = grid("60", 3, 8, 6, 8, 20)
        self.a_annotation = self.mark("a-mark", self.a, timing=self.a_timing)
        self.b_annotation = self.mark("b-mark", self.b, timing=self.b_timing)
        runtime = patch.dict("os.environ", {"SCORE_MATTER_SA3_ROOT": str(self.root / "absent-runtime")})
        runtime.start()
        self.addCleanup(runtime.stop)
        for name in ("score_matter.authoring.subprocess.run", "score_matter.sa3_edit.run_process"):
            mocked = patch(name, side_effect=AssertionError("Arrangement must never launch a model"))
            backend = mocked.start()
            self.addCleanup(mocked.stop)
            self.addCleanup(backend.assert_not_called)

    def source(self, identifier, *, rate=8000, channels=1, bias=0, frames=5000):
        pcm = PCM(sample_bytes(array("h", [(bias + i % 61 - 30) * (1 if channel == 0 else -1)
                  for i in range(frames) for channel in range(channels)])), rate, channels)
        path = self.root / (identifier + ".wav")
        path.write_bytes(encode_wav(pcm))
        return self.store.import_wav(path, identifier)["outputs"][0], path, pcm

    def mark(self, identifier, audio, *, timing=None, region_id="phrase", start=None, end=None, source="agent"):
        request = {"schema": "score-music-annotate/v1", "request_id": identifier,
            "asset_id": audio["asset_id"], "source": source,
            "timing": {"mode": "free"} if timing is None else timing,
            "regions": [{"id": region_id,
                         "start": ({"bar": 1, "beat": "1"} if timing else {"frame": 2}) if start is None else start,
                         "end": ({"bar": 1, "beat": "2"} if timing else {"frame": 6}) if end is None else end}]}
        return annotate(self.store, request)["outputs"][0]

    def segment(self, identifier, annotation, repeat=1, region_id="phrase"):
        return {"id": identifier, "annotation_id": annotation["asset_id"], "region_id": region_id, "repeat": repeat}

    def request(self, request_id="arrange", segments=None):
        return {"schema": "score-music-arrange/v1", "request_id": request_id,
                "segments": [self.segment("intro", self.a_annotation), self.segment("body", self.b_annotation, 2),
                             self.segment("outro", self.a_annotation)] if segments is None else segments}

    def call(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["audio", "--workspace", str(self.store.root), *map(str, arguments), "--json"])
        return code, json.loads(output.getvalue())

    def cli_request(self, request):
        path = self.root / "arrangement.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        return self.call("music", "arrange", "--request", path)

    def counts(self):
        return tuple(len(list((self.store.root / directory).iterdir())) for directory in ("objects", "requests"))

    def test_cli_arranges_exact_pcm_in_order_with_integer_repeats_and_distinct_grids(self):
        code, capability = self.call("capabilities")
        self.assertEqual(code, 0)
        self.assertIn("score-music-arrange/v1", json.dumps(capability["product_capabilities"]))
        before = self.counts()
        code, planned = self.cli_request(self.request())
        self.assertEqual(code, 0)
        self.assertEqual(self.counts(), tuple(value + 1 for value in before))
        self.assertEqual([item["role"] for item in planned["outputs"]], ["music_arrangement"])
        plan_id = planned["outputs"][0]["asset_id"]
        code, saved = self.call("music", "show", plan_id)
        self.assertEqual(code, 0)
        document = saved["document"]
        self.assertEqual(document["duration_frames"], 13334)
        self.assertEqual([(item["start_frame"], item["end_frame"]) for item in document["timeline"]],
                         [(0, 4000), (4000, 6667), (6667, 9334), (9334, 13334)])
        self.assertEqual([item["repeat_index"] for item in document["timeline"]], [0, 0, 1, 0])
        self.assertEqual(self.call("action", "show", document["core_request"]["request_id"])[1]["error"]["code"], "request_not_found")
        code, result = self.call("music", "execute", plan_id)
        self.assertEqual(code, 0)
        pcm = decode_wav(self.store.asset(result["outputs"][0]["asset_id"])[1])
        a_section, b_section = self.a_pcm.payload[20:8020], self.b_pcm.payload[40:5374]
        self.assertEqual(pcm.payload, a_section + b_section * 2 + a_section)
        self.assertEqual(pcm.frames, 13334)
        self.assertEqual(result["audio_model_calls"], 0)
        self.assertFalse((self.store.root / "sessions.sqlite3").exists())
        self.assertEqual(self.call("music", "show", plan_id), (0, saved))

    def test_identity_keeps_distinct_assets_with_equal_bytes_and_all_annotation_sources(self):
        duplicate = self.store.import_wav(self.a_path, "a-distinct-id")["outputs"][0]
        self.assertEqual(duplicate["digest"], self.a["digest"])
        self.assertNotEqual(duplicate["asset_id"], self.a["asset_id"])
        other_mark = self.mark("a-other-mark", self.a, timing=self.a_timing, source="project")
        duplicate_mark = self.mark("a-duplicate-mark", duplicate, timing=self.a_timing)
        planned = arrange(self.store, self.request(segments=[self.segment("one", self.a_annotation),
            self.segment("two", other_mark), self.segment("three", duplicate_mark)]))
        document = show(self.store, planned["outputs"][0]["asset_id"])["document"]
        self.assertEqual([item["asset_id"] for item in document["inputs"]], [self.a["asset_id"], duplicate["asset_id"]])
        self.assertEqual([item["input_index"] for item in document["segments"]], [0, 0, 1])
        self.assertEqual([item["annotation"]["asset_id"] for item in document["segments"]],
                         [self.a_annotation["asset_id"], other_mark["asset_id"], duplicate_mark["asset_id"]])
        result = execute(self.store, planned["outputs"][0]["asset_id"])
        self.assertEqual({item["asset_id"] for item in result["music_annotations"]},
                         {self.a_annotation["asset_id"], other_mark["asset_id"], duplicate_mark["asset_id"]})
        self.assertEqual({item["asset_id"] for item in result["outputs"][0]["parents"]},
                         {self.a["asset_id"], duplicate["asset_id"]})

    def test_arrangement_keeps_sources_sessions_feedback_and_locks_unchanged(self):
        self.sessions.mutate("create", {"schema": "matter-session-create/v1", "request_id": "session",
            "session_id": "existing", "name": "Existing source work", "asset_id": self.a["asset_id"]})
        self.sessions.mutate("constraints", {"schema": "matter-constraints-set/v1", "request_id": "locks",
            "session_id": "existing", "expected_revision": 1, "regions": [{"start_frame": 10, "end_frame": 20}]})
        self.sessions.mutate("feedback", {"schema": "matter-feedback/v1", "request_id": "note", "session_id": "existing",
            "revision": 2, "source": "agent", "text": "Synthetic test note; no listening performed."})
        before = self.call("context", "show", "existing")
        source_bytes = (self.a_path.read_bytes(), self.b_path.read_bytes())
        annotation_documents = [show(self.store, item["asset_id"]) for item in (self.a_annotation, self.b_annotation)]
        planned = arrange(self.store, self.request())
        result = execute(self.store, planned["outputs"][0]["asset_id"])
        self.assertEqual(self.call("context", "show", "existing"), before)
        self.assertEqual((self.a_path.read_bytes(), self.b_path.read_bytes()), source_bytes)
        self.assertEqual([show(self.store, item["asset_id"]) for item in (self.a_annotation, self.b_annotation)], annotation_documents)
        self.assertEqual([item["role"] for item in result["outputs"]], ["audio"])
        self.assertNotIn("protection", result["findings"][0])
        with self.assertRaises(AudioError):
            show(self.store, result["outputs"][0]["asset_id"])
        with self.assertRaises(AudioError) as caught:
            self.sessions.mutate("select", {"schema": "matter-session-select/v1", "request_id": "inherit-old-locks",
                "session_id": "existing", "expected_revision": 2, "asset_id": result["outputs"][0]["asset_id"]})
        self.assertEqual(caught.exception.code, "constraint_mapping_unavailable")
        self.assertEqual(self.call("context", "show", "existing"), before)
        self.sessions.mutate("create", {"schema": "matter-session-create/v1", "request_id": "explicit-new-session",
            "session_id": "new-output", "name": "Explicit result session", "asset_id": result["outputs"][0]["asset_id"]})
        self.assertEqual(self.sessions.show("new-output")["protected_regions"], [])

    def test_completed_plan_and_execution_replay_or_conflict_without_overwrite(self):
        request = self.request()
        planned = arrange(self.store, request)
        plan_id = planned["outputs"][0]["asset_id"]
        saved = show(self.store, plan_id)
        result = execute(self.store, plan_id)
        self.assertEqual(arrange(self.store, request), planned)
        self.assertEqual(execute(self.store, plan_id), result)
        changed = copy.deepcopy(request)
        changed["segments"][1]["repeat"] = 3
        with self.assertRaises(AudioError) as caught:
            arrange(self.store, changed)
        self.assertEqual(caught.exception.code, "request_conflict")
        self.assertEqual(show(self.store, plan_id), saved)
        self.assertEqual(execute(self.store, plan_id), result)

    def test_unsupported_controls_are_rejected_at_both_request_and_segment_levels(self):
        count = self.counts()
        controls = {"protection": {"session_id": "absent", "revision": 1}, "gap_frames": 1,
                    "overlap_frames": 1, "db": -6, "gain": 0.5, "tempo": "120", "offset_frame": 4}
        for key, value in controls.items():
            for level in ("request", "segment"):
                request = self.request()
                target = request if level == "request" else request["segments"][0]
                target[key] = value
                with self.subTest(key=key, level=level), self.assertRaises(AudioError) as caught:
                    arrange(self.store, request)
                self.assertEqual(caught.exception.code, "invalid_request")
                self.assertEqual(self.counts(), count)

    def test_invalid_counts_identifiers_and_missing_regions_fail_before_claim(self):
        cases = []
        for value in (0, -1, 65, 2.0, True):
            request = self.request()
            request["segments"][0]["repeat"] = value
            cases.append((request, "invalid_request"))
        for segments in ([], [self.segment("s" + str(i), self.a_annotation) for i in range(129)]):
            cases.append((self.request(segments=segments), "invalid_request"))
        cases.append((self.request(segments=[self.segment("same", self.a_annotation), self.segment("same", self.b_annotation)]), "duplicate_music_segment"))
        cases.append((self.request(segments=[self.segment("missing", self.a_annotation, region_id="absent")]), "music_region_not_found"))
        cases.append((self.request(segments=[self.segment("audio-not-annotation", self.a)]), "invalid_music_annotation"))
        cases.append((self.request(segments=[self.segment("s" + str(i), self.a_annotation, 64) for i in range(17)]), "music_arrangement_limit"))
        count = self.counts()
        for request, error in cases:
            with self.subTest(error=error, segments=len(request["segments"])), self.assertRaises(AudioError) as caught:
                arrange(self.store, request)
            self.assertEqual(caught.exception.code, error)
            self.assertEqual(self.counts(), count)

    def test_arrangement_rejects_sample_rate_or_channel_conversion(self):
        for identifier, rate, channels in (("different-rate", 16000, 1), ("different-channels", 8000, 2)):
            audio, _, _ = self.source(identifier, rate=rate, channels=channels)
            annotation = self.mark(identifier + "-mark", audio)
            count = self.counts()
            with self.subTest(identifier=identifier), self.assertRaises(AudioError) as caught:
                arrange(self.store, self.request(segments=[self.segment("a", self.a_annotation), self.segment("other", annotation)]))
            self.assertEqual(caught.exception.code, "music_arrangement_format_mismatch")
            self.assertEqual(self.counts(), count)

    def test_seventeen_distinct_assets_are_not_deduplicated_by_audio_hash(self):
        segments = []
        for index in range(17):
            audio = self.store.import_wav(self.a_path, "duplicate-" + str(index))["outputs"][0]
            annotation = self.mark("mark-" + str(index), audio)
            segments.append(self.segment("s" + str(index), annotation))
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            arrange(self.store, self.request(segments=segments))
        self.assertEqual(caught.exception.code, "music_arrangement_limit")
        self.assertEqual(self.counts(), count)

    def test_output_capacity_is_checked_during_planning_without_rendering_large_audio(self):
        # A 4 MB source would become 68 MB after seventeen repeats. No large
        # output is rendered; sixteen repeats still fit the Core output budget.
        path = self.root / "capacity.wav"
        path.write_bytes(encode_wav(PCM(b"\0\0" * 2000000, 8000, 1)))
        audio = self.store.import_wav(path, "capacity-source")["outputs"][0]
        annotation = self.mark("capacity-mark", audio, start={"frame": 0}, end={"frame": 2000000})
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            arrange(self.store, self.request(segments=[self.segment("large", annotation, 17)]))
        self.assertEqual(caught.exception.code, "output_limit")
        self.assertEqual(self.counts(), count)
        planned = arrange(self.store, self.request(segments=[self.segment("large", annotation, 16)]))
        self.assertEqual(planned["document"]["duration_frames"], 32000000)
        self.assertEqual([item["role"] for item in planned["outputs"]], ["music_arrangement"])

    def test_maximum_occurrences_and_long_ids_never_publish_an_unreadable_receipt(self):
        identifier = "r" * 96
        annotation = self.mark("m" * 96, self.a, region_id=identifier)
        segments = [self.segment("s" + str(index).zfill(3) + "x" * 92, annotation, 8, identifier) for index in range(128)]
        request = self.request("q" * 96, segments)
        count = self.counts()
        try:
            planned = arrange(self.store, request)
        except AudioError as exc:
            self.assertEqual(exc.code, "json_too_large")
            self.assertEqual(self.counts(), count)
        else:
            self.assertEqual(self.store.show_request(request["request_id"]), planned)
            self.assertEqual(show(self.store, planned["outputs"][0]["asset_id"])["document"], planned["document"])
            self.assertEqual(len(planned["document"]["timeline"]), 1024)

    def test_unfinished_plan_and_execution_claims_remain_pending_without_new_requests(self):
        publication = self.store._publish

        def interrupt_result(target, files):
            if target.parent.name == "objects":
                raise OSError("Synthetic interrupted arrangement publication")
            return publication(target, files)

        with patch.object(self.store, "_publish", side_effect=interrupt_result), self.assertRaises(OSError):
            arrange(self.store, self.request("pending-plan"))
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            arrange(self.store, self.request("pending-plan"))
        self.assertEqual(caught.exception.code, "recovery_pending")
        self.assertEqual(self.counts(), count)
        planned = arrange(self.store, self.request("ready-plan"))
        plan_id = planned["outputs"][0]["asset_id"]
        with patch.object(self.store, "_publish", side_effect=interrupt_result), self.assertRaises(OSError):
            execute(self.store, plan_id)
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            execute(self.store, plan_id)
        self.assertEqual(caught.exception.code, "recovery_pending")
        self.assertEqual(self.counts(), count)

    def test_saved_timeline_refs_and_core_request_cannot_be_forged(self):
        planned = arrange(self.store, self.request())
        original = show(self.store, planned["outputs"][0]["asset_id"])["document"]
        cases = [
            (("timeline", 1, "start_frame"), 4001),
            (("duration_frames",), 13335),
            (("segments", 1, "annotation", "asset_id"), self.a_annotation["asset_id"]),
            (("segments", 1, "audio", "asset_id"), self.a["asset_id"]),
            (("segments", 1, "audio", "digest"), {"algorithm": "sha256", "hex": "0" * 64}),
            (("segments", 1, "region", "start_frame"), 21),
            (("core_request", "parameters", "events", 1, "offset_frame"), 4001),
        ]
        for index, (keys, value) in enumerate(cases):
            document = copy.deepcopy(original)
            target = document
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value

            def publish(publication):
                publication.add(canonical(document), {"kind": "music_arrangement", "content_type": "application/json"},
                                role="music_arrangement", parents=planned["outputs"][0]["parents"])
                return {}

            forged = self.store.transact("forged-" + str(index), {"fixture": index}, publish)
            count = self.counts()
            for operation in (show, execute):
                with self.subTest(keys=keys, operation=operation.__name__), self.assertRaises(AudioError) as caught:
                    operation(self.store, forged["outputs"][0]["asset_id"])
                self.assertEqual(caught.exception.code, "music_binding_mismatch")
            self.assertEqual(self.counts(), count)

    def test_corrupt_source_annotation_is_rejected_when_loading_an_existing_plan(self):
        planned = arrange(self.store, self.request())
        (self.store.root / self.b_annotation["locator"]).write_bytes(b"{}")
        count = self.counts()
        for operation in (show, execute):
            with self.subTest(operation=operation.__name__), self.assertRaises(AudioError) as caught:
                operation(self.store, planned["outputs"][0]["asset_id"])
            self.assertEqual(caught.exception.code, "integrity_error")
        self.assertEqual(self.counts(), count)


if __name__ == "__main__":
    unittest.main()
