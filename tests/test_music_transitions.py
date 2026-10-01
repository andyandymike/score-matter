"""Explicit occurrence seams use measured PCM, not inferred musical alignment."""
from __future__ import annotations

import contextlib
import copy
import hashlib
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
    raise unittest.SkipTest("Install the optional audio dependency for music transition tests") from exc

from matter_audio_core.artifacts import ArtifactStore
from matter_audio_core.contracts import canonical
from matter_audio_core.errors import AudioError
from matter_audio_core.media import PCM, decode_wav, encode_wav, sample_bytes
from score_matter.cli import main
from score_matter.music import annotate, arrange, execute, show


class TransitionFixture(unittest.TestCase):
    """Shared tiny inputs; this base deliberately defines no test methods."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.store = ArtifactStore(self.root / "workspace", product="score-matter")
        self.a, self.a_mark = self.source("a", [91, 100, 200, 300, 400, 500, 600, 92], 1, 7)
        self.b, self.b_mark = self.source("b", [81, 82, 1000, 2000, 3000, 4000, 5000, 6000, 83], 2, 8)
        runtime = patch.dict("os.environ", {"SCORE_MATTER_SA3_ROOT": str(self.root / "absent-runtime")})
        runtime.start()
        self.addCleanup(runtime.stop)
        for name in ("score_matter.authoring.subprocess.run", "score_matter.sa3_edit.run_process"):
            mocked = patch(name, side_effect=AssertionError("Musical finishing must not launch a model"))
            backend = mocked.start()
            self.addCleanup(mocked.stop)
            self.addCleanup(backend.assert_not_called)

    def source(self, identifier, samples, start, end):
        path = self.root / (identifier + ".wav")
        path.write_bytes(encode_wav(PCM(sample_bytes(array("h", samples)), 8000, 1)))
        audio = self.store.import_wav(path, identifier)["outputs"][0]
        marking = annotate(self.store, {"schema": "score-music-annotate/v1", "request_id": identifier + "-mark",
            "asset_id": audio["asset_id"], "source": "agent", "timing": {"mode": "free"},
            "regions": [{"id": "phrase", "start": {"frame": start}, "end": {"frame": end}}]})["outputs"][0]
        return audio, marking

    def segment(self, identifier, marking=None, repeat=1):
        return {"id": identifier, "annotation_id": (marking or self.a_mark)["asset_id"], "region_id": "phrase", "repeat": repeat}

    def transition(self, identifier="a-repeat", repeat_index=1, frames=3):
        return {"after_segment_id": identifier, "after_repeat_index": repeat_index, "crossfade_frames": frames}

    def request(self, request_id="transition-plan", *, segments=None, transitions=None):
        return {"schema": "score-music-arrange/v2", "request_id": request_id,
            "segments": [self.segment("a-repeat", repeat=2), self.segment("b", self.b_mark)] if segments is None else segments,
            "transitions": [self.transition()] if transitions is None else transitions}

    def legacy_request(self):
        request = self.request("legacy-golden")
        request["schema"] = "score-music-arrange/v1"
        del request["transitions"]
        return request

    def call(self, *arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["audio", "--workspace", str(self.store.root), *map(str, arguments), "--json"])
        return code, json.loads(output.getvalue())

    def cli_request(self, command, request):
        path = self.root / "request.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        return self.call("music", command, "--request", path)

    def samples(self, result):
        return list(decode_wav(self.store.asset(result["outputs"][0]["asset_id"])[1]).samples())

    def counts(self):
        return tuple(len(list((self.store.root / directory).iterdir())) for directory in ("objects", "requests"))

    def forge(self, document, original_record, identifier="forged"):
        def publish(publication):
            publication.add(canonical(document), original_record["media"], role=original_record["role"],
                            parents=original_record["parents"])
            return {}
        return self.store.transact(identifier, {"fixture": identifier}, publish)["outputs"][0]["asset_id"]

    def normalized_legacy(self, result):
        document = result["document"]
        replacements = {
            self.a["asset_id"]: "A", self.b["asset_id"]: "B",
            self.a_mark["asset_id"]: "A_MARK", self.b_mark["asset_id"]: "B_MARK",
            self.a_mark["digest"]["hex"]: "A_MARK_DIGEST", self.b_mark["digest"]["hex"]: "B_MARK_DIGEST",
            document["core_request"]["request_id"]: "CORE_REQUEST",
            document["core_resolution"]["digest"]["hex"]: "CORE_RESOLUTION_DIGEST",
        }

        def normalize(value):
            if isinstance(value, str):
                return replacements.get(value, value)
            if isinstance(value, list):
                return [normalize(item) for item in value]
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in value.items()}
            return value
        return canonical(normalize({"binding": result["binding"], "document": document}))


class MusicTransitionTests(TransitionFixture):
    def test_only_the_requested_repeat_seam_crossfades_with_exact_linear_pcm(self):
        code, planned = self.cli_request("arrange", self.request())
        self.assertEqual(code, 0)
        plan_id = planned["outputs"][0]["asset_id"]
        document = show(self.store, plan_id)["document"]
        self.assertEqual(document["schema"], "score-music-arrangement-plan/v2")
        self.assertEqual(document["duration_frames"], 15)
        self.assertEqual([(item["start_frame"], item["end_frame"], item["body_start_frame"], item["body_end_frame"])
                          for item in document["timeline"]], [(0, 6, 0, 6), (6, 12, 6, 9), (9, 15, 12, 15)])
        result = execute(self.store, plan_id)
        self.assertEqual(self.samples(result), [100, 200, 300, 400, 500, 600,
            100, 200, 300, 400, 1250, 3000, 4000, 5000, 6000])
        self.assertEqual(result["audio_model_calls"], 0)
        self.assertEqual(execute(self.store, plan_id), result)
        self.assertEqual(self.cli_request("arrange", self.request()), (0, planned))
        self.assertFalse((self.store.root / "sessions.sqlite3").exists())

    def test_two_and_four_frame_seams_preserve_endpoints_and_round_once(self):
        segments = [self.segment("a"), self.segment("b", self.b_mark)]
        expected = {2: [100, 200, 300, 400, 500, 2000, 3000, 4000, 5000, 6000],
                    4: [100, 200, 300, 933, 2167, 4000, 5000, 6000]}
        for fade, samples in expected.items():
            planned = arrange(self.store, self.request("fade-" + str(fade), segments=segments,
                transitions=[self.transition("a", 0, fade)]))
            self.assertEqual(self.samples(execute(self.store, planned["outputs"][0]["asset_id"])), samples)

    def test_v2_with_no_transitions_is_exact_concatenation(self):
        planned = arrange(self.store, self.request(transitions=[]))
        self.assertEqual(planned["document"]["duration_frames"], 18)
        result = execute(self.store, planned["outputs"][0]["asset_id"])
        self.assertEqual(self.samples(result), [100, 200, 300, 400, 500, 600] * 2 + [1000, 2000, 3000, 4000, 5000, 6000])

    def test_invalid_boundary_identity_and_schema_fail_before_claim(self):
        transitions = [[self.transition("missing")], [self.transition("a-repeat", 2)],
            [self.transition("b", 0)], [self.transition(), self.transition()]]
        for value in (0, 1, -1, 2.0, True):
            transitions.append([self.transition(frames=value)])
        requests = [self.request(transitions=value) for value in transitions]
        absent = self.request()
        del absent["transitions"]
        requests.append(absent)
        legacy = self.legacy_request()
        legacy["transitions"] = []
        requests.append(legacy)
        extra = self.request()
        extra["transitions"][0]["curve"] = "equal_power"
        requests.append(extra)
        count = self.counts()
        for request in requests:
            with self.subTest(request=request), self.assertRaises(AudioError):
                arrange(self.store, request)
            self.assertEqual(self.counts(), count)

    def test_short_regions_and_triple_overlap_are_rejected_but_empty_middle_body_is_valid_audio(self):
        _, short = self.source("short", [10, 20], 0, 1)
        requests = [self.request(segments=[self.segment("a", short), self.segment("b", self.b_mark)],
                    transitions=[self.transition("a", 0, 2)]),
                    self.request(segments=[self.segment("a"), self.segment("middle", self.b_mark), self.segment("end")],
                    transitions=[self.transition("a", 0, 4), self.transition("middle", 0, 3)])]
        count = self.counts()
        for request in requests:
            with self.assertRaises(AudioError):
                arrange(self.store, request)
            self.assertEqual(self.counts(), count)
        planned = arrange(self.store, self.request(segments=[self.segment("a"), self.segment("middle", self.b_mark), self.segment("end")],
            transitions=[self.transition("a", 0, 3), self.transition("middle", 0, 3)]))
        middle = planned["document"]["timeline"][1]
        self.assertEqual(middle["body_start_frame"], middle["body_end_frame"])

    def test_event_definition_limit_and_repeat_compression_are_not_occurrence_limits(self):
        def alternating(segments):
            occurrences = [(item["id"], index) for item in segments for index in range(item["repeat"])]
            return [self.transition(identifier, index, 2 + position % 2)
                    for position, (identifier, index) in enumerate(occurrences[:-1])]
        segments = [self.segment("a", repeat=64), self.segment("b", repeat=64)]
        planned = arrange(self.store, self.request("event-boundary", segments=segments, transitions=alternating(segments)))
        self.assertEqual(len(planned["document"]["core_request"]["parameters"]["events"]), 128)
        segments.append(self.segment("c", repeat=64))
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            arrange(self.store, self.request("too-many-events", segments=segments, transitions=alternating(segments)))
        self.assertEqual(caught.exception.code, "music_arrangement_event_limit")
        self.assertEqual(self.counts(), count)
        repeated = [self.segment("s" + str(index), repeat=64) for index in range(16)]
        occurrences = [(item["id"], index) for item in repeated for index in range(64)]
        transitions = [self.transition(identifier, index, 2) for identifier, index in occurrences[:-1]]
        count = self.counts()
        try:
            compressed = arrange(self.store, self.request("max-occurrences", segments=repeated, transitions=transitions))
        except AudioError as exc:
            self.assertEqual(exc.code, "json_too_large")
            self.assertEqual(self.counts(), count)
        else:
            self.assertEqual(len(compressed["document"]["timeline"]), 1024)
            self.assertLessEqual(len(compressed["document"]["core_request"]["parameters"]["events"]), 128)
            self.assertEqual(self.store.show_request("max-occurrences"), compressed)
        with self.assertRaises(AudioError) as caught:
            arrange(self.store, self.request("over-occurrences", segments=[*repeated, self.segment("extra", repeat=64)], transitions=[]))
        self.assertEqual(caught.exception.code, "music_arrangement_limit")

    def test_saved_seam_timeline_and_core_events_are_checked_with_valid_parents(self):
        planned = arrange(self.store, self.request())
        original = planned["document"]
        cases = [(('duration_frames',), 16), (("timeline", 1, "fade_out_frames"), 2),
            (("timeline", 2, "body_start_frame"), 11),
            (("core_request", "parameters", "events", 0, "fade_out_frames"), 1)]
        for index, (keys, value) in enumerate(cases):
            document = copy.deepcopy(original)
            target = document
            for key in keys[:-1]:
                target = target[key]
            target[keys[-1]] = value
            forged = self.forge(document, planned["outputs"][0], "forged-seam-" + str(index))
            count = self.counts()
            for operation in (show, execute):
                with self.subTest(keys=keys, operation=operation.__name__), self.assertRaises(AudioError) as caught:
                    operation(self.store, forged)
                self.assertEqual(caught.exception.code, "music_binding_mismatch")
            self.assertEqual(self.counts(), count)

    def test_changed_seam_request_conflicts_and_incomplete_execution_remains_pending(self):
        planned = arrange(self.store, self.request())
        with self.assertRaises(AudioError) as caught:
            arrange(self.store, self.request(transitions=[self.transition(frames=2)]))
        self.assertEqual(caught.exception.code, "request_conflict")
        publication = self.store._publish

        def interrupt_result(target, files):
            if target.parent.name == "objects":
                raise OSError("Synthetic transition interruption")
            return publication(target, files)

        with patch.object(self.store, "_publish", side_effect=interrupt_result), self.assertRaises(OSError):
            execute(self.store, planned["outputs"][0]["asset_id"])
        count = self.counts()
        with self.assertRaises(AudioError) as caught:
            execute(self.store, planned["outputs"][0]["asset_id"])
        self.assertEqual(caught.exception.code, "recovery_pending")
        self.assertEqual(self.counts(), count)

    def test_v1_binding_and_document_match_the_pre_transition_golden(self):
        planned = arrange(self.store, self.legacy_request())
        # Canonical v1 binding/document from published Score 02434ca8, with only
        # random asset IDs and their derived reference digests normalized.
        self.assertEqual(hashlib.sha256(self.normalized_legacy(planned)).hexdigest(),
                         "6dcf1173cfe7562f7aca49f018f5c7b06f629c91d315024f42e229cbe5dfcb65")
        self.assertEqual(planned["document"]["schema"], "score-music-arrangement-plan/v1")
        self.assertNotIn("transitions", planned["document"])
        result = execute(self.store, planned["outputs"][0]["asset_id"])
        self.assertEqual(arrange(self.store, self.legacy_request()), planned)
        self.assertEqual(execute(self.store, planned["outputs"][0]["asset_id"]), result)


if __name__ == "__main__":
    unittest.main()
