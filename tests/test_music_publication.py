"""Public Core boundaries protect complete metadata without changing saved music."""
from __future__ import annotations

import copy
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
    raise unittest.SkipTest("Install the optional audio dependency for music publication tests") from exc

from matter_audio_core.artifacts import ArtifactStore, Publication
from matter_audio_core.contracts import MAX_JSON_BYTES, canonical
from matter_audio_core.errors import AudioError
from matter_audio_core.media import PCM, encode_wav, sample_bytes
from matter_audio_core.sessions import SessionService
from score_matter.music import annotate, annotate_arrangement, arrange, execute, plan, show
from score_matter.music_publication import validated_producer


class MusicPublicationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = ArtifactStore(self.root / "workspace", product="score-matter")
        source = self.root / "source.wav"
        source.write_bytes(encode_wav(PCM(sample_bytes(array("h", range(100))), 8000, 1)))
        self.audio = self.store.import_wav(source, "audio")["outputs"][0]
        self.annotation_request = {"schema": "score-music-annotate/v1", "request_id": "annotation",
            "asset_id": self.audio["asset_id"], "source": "user", "timing": {"mode": "unknown"},
            "regions": [{"id": "phrase", "start": {"frame": 10}, "end": {"frame": 40}}]}
        self.annotation = annotate(self.store, self.annotation_request)
        self.arrangement_request = {"schema": "score-music-arrange/v1", "request_id": "arrangement",
            "segments": [{"id": "intro", "annotation_id": self.annotation["outputs"][0]["asset_id"],
                          "region_id": "phrase", "repeat": 2}]}
        self.arrangement = arrange(self.store, self.arrangement_request)
        execute(self.store, self.arrangement["outputs"][0]["asset_id"])

    def test_every_music_publisher_checks_complete_receipt_before_claim(self):
        trim = {"schema": "score-music-plan/v1", "request_id": "trim",
                "annotation_id": self.annotation["outputs"][0]["asset_id"],
                "region_ids": ["phrase"], "target": {"kind": "trim"}}
        transitions = {**self.arrangement_request, "schema": "score-music-arrange/v2", "transitions": []}
        derived = {"schema": "score-music-annotate-arrangement/v1", "request_id": "derived",
            "plan_id": self.arrangement["outputs"][0]["asset_id"], "source": "project",
            "regions": [{"id": "intro", "segment_id": "intro", "repeat_index": 0, "range": "body"}]}
        original = self.store.validate_publication
        for index, (publish, request) in enumerate(((annotate, self.annotation_request), (plan, trim),
                (arrange, self.arrangement_request), (arrange, transitions), (annotate_arrangement, derived))):
            with self.subTest(publisher=publish.__name__, schema=request["schema"]):
                request = {**request, "request_id": f"reject-{index}"}
                seen = []

                def validate_complete(request_id, binding, publication, extra, **kwargs):
                    if request_id == request["request_id"]:
                        # The document itself fits. Core must account for the entire receipt.
                        document_size = len(canonical(extra["document"]))
                        seen.append(document_size)
                        with patch("matter_audio_core.artifacts.MAX_JSON_BYTES", document_size + 1):
                            return original(request_id, binding, publication, extra, **kwargs)
                    return original(request_id, binding, publication, extra, **kwargs)

                before = sorted(str(path.relative_to(self.store.root)) for path in self.store.root.rglob("*"))
                with patch.object(self.store, "validate_publication", side_effect=validate_complete):
                    with self.assertRaises(AudioError) as failure:
                        publish(self.store, request)
                self.assertEqual(failure.exception.code, "json_too_large")
                self.assertEqual(failure.exception.__cause__.code, "publication_too_large")
                self.assertEqual(len(seen), 1)
                self.assertEqual(before, sorted(str(path.relative_to(self.store.root)) for path in self.store.root.rglob("*")))
                with self.assertRaises(AudioError) as missing:
                    self.store.show_request(request["request_id"])
                self.assertEqual(missing.exception.code, "request_not_found")

    def test_real_one_mib_limit_includes_binding_and_metadata(self):
        store = ArtifactStore(self.root / "untouched", product="score-matter")
        document = {"content": "x" * 300000}
        self.assertLess(len(canonical(document)), MAX_JSON_BYTES)
        with self.assertRaises(AudioError) as failure:
            validated_producer(store, "oversized", {"document": document, "padding": "y" * 500000},
                               document, "music_annotation", [], [])
        self.assertEqual(failure.exception.code, "json_too_large")
        self.assertFalse(store.root.exists())

    def test_same_producer_matches_actual_receipt_and_preserves_replay(self):
        document = {"schema": "test-document/v1", "content": "x" * 100000}
        binding = {"document": document}
        produce = validated_producer(self.store, "exact-preview", binding, document, "music_annotation", [], [])
        result = self.store.transact("exact-preview", binding, produce)
        preview = Publication(result["group_id"])
        expected = self.store.validate_publication("exact-preview", binding, preview, produce(preview))
        self.assertEqual(result, expected)
        self.assertEqual(result, self.store.show_request("exact-preview"))
        self.assertEqual(result, self.store.transact("exact-preview", binding, produce))

    def test_constraints_use_only_public_historical_revision_after_head_changes(self):
        sessions = SessionService(self.store)
        sessions.mutate("create", {"schema": "matter-session-create/v1", "request_id": "create",
            "session_id": "music", "name": "Music", "asset_id": self.audio["asset_id"]})
        request = {"schema": "score-music-plan/v1", "request_id": "locks-plan",
            "annotation_id": self.annotation["outputs"][0]["asset_id"], "region_ids": ["phrase"],
            "target": {"kind": "constraints", "session_id": "music", "expected_revision": 1}}

        class PublicSessions:
            def revision(self, session_id, revision):
                return sessions.revision(session_id, revision)

            def constraints(self, session_id, *, revision):
                return sessions.constraints(session_id, revision=revision)

            def show(self, session_id):
                return sessions.show(session_id)

            def mutate(self, operation, body):
                return sessions.mutate(operation, body)

        public = PublicSessions()
        with patch("score_matter.music.SessionService", return_value=public):
            saved = plan(self.store, request)
            plan_id = saved["outputs"][0]["asset_id"]
            first = execute(self.store, plan_id)
            sessions.mutate("constraints", {"schema": "matter-constraints-set/v1", "request_id": "unlock",
                "session_id": "music", "expected_revision": 2, "regions": []})
            with patch.object(public, "show", side_effect=AssertionError("Historical load must not inspect today's head")):
                self.assertEqual(show(self.store, plan_id)["document"], saved["document"])
                self.assertEqual(execute(self.store, plan_id), first)
                self.assertEqual(plan(self.store, copy.deepcopy(request)), saved)
        self.assertEqual(sessions.show("music")["current"]["revision"], 3)


if __name__ == "__main__":
    unittest.main()
