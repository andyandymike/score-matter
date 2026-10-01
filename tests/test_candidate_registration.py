"""Candidate intake uses existing synthetic PCM only, never model generation."""
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
    raise unittest.SkipTest("Install the optional audio dependency for candidate registration tests") from exc

from matter_audio_core.artifacts import ArtifactStore
from matter_audio_core.contracts import digest
from matter_audio_core.errors import AudioError
from matter_audio_core.media import PCM, encode_wav, sample_bytes
from score_matter.candidates import register_candidate
from score_matter.cli import main


class CandidateRegistrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.workspace = self.root / "workspace"
        self.store = ArtifactStore(self.workspace, product="score-matter")
        self.audio = self.root / "existing candidate.wav"
        self.audio.write_bytes(encode_wav(PCM(sample_bytes(array("h", [-1000, 0, 1000] * 20)), 8000, 1)))
        self.record = self.root / "generation.json"
        self.record_document = {
            "kind": "score-matter-fast-generation", "status": "candidate",
            "prompt": "Synthetic fixture; no generation occurred.",
            "output": {"path": "historical/path/never-opened.wav",
                       "sha256": "sha256:" + digest(self.audio.read_bytes())["hex"],
                       "media": {"container": "wav", "codec": "pcm_s16le", "sample_rate_hz": 8000,
                                 "channels": 1, "sample_width_bytes": 2, "frame_count": 60}},
        }
        self.record.write_text(json.dumps(self.record_document, indent=2) + "\n", encoding="utf-8")
        self.intent = self.root / "intent.json"
        self.intent_document = {"schema": "score-music-intent/v1", "source": "agent",
                                "purpose": "工程用候选", "preserve": ["Existing audio"], "change": []}
        self.intent.write_text(json.dumps(self.intent_document, ensure_ascii=False, indent=2), encoding="utf-8")
        runtime = patch.dict("os.environ", {"SCORE_MATTER_SA3_ROOT": str(self.root / "absent-runtime")})
        runtime.start()
        self.addCleanup(runtime.stop)
        for name in ("score_matter.authoring.subprocess.run", "score_matter.sa3_edit.run_process"):
            mocked = patch(name, side_effect=AssertionError("Registration must never launch a model"))
            backend = mocked.start()
            self.addCleanup(mocked.stop)
            self.addCleanup(backend.assert_not_called)

    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["audio", "--workspace", str(self.workspace), *map(str, args), "--json"])
        return code, json.loads(output.getvalue())

    def register(self, request_id="register", **overrides):
        options = {"generation_record": self.record, "intent": self.intent, **overrides}
        return register_candidate(self.store, self.audio, request_id, **options)

    def mutation(self, command, body):
        path = self.root / "session-request.json"
        path.write_text(json.dumps(body), encoding="utf-8")
        return self.call(*command, "--request", path)

    def test_capabilities_describe_files_schema_and_verification_limits(self):
        code, response = self.call("capabilities")
        self.assertEqual(code, 0)
        capability = response["product_capabilities"]["candidate_registration"]
        self.assertEqual(capability["command"], "candidate register")
        self.assertEqual(capability["file_parameters"], ["--audio", "--generation-record", "--intent"])
        self.assertEqual(capability["intent_schema"]["properties"]["schema"]["const"], "score-music-intent/v1")
        self.assertIn("model weights are not verified", " ".join(capability["limitations"]))
        self.assertFalse(self.workspace.exists())

    def test_cli_keeps_exact_audio_and_attachment_bytes_in_one_group(self):
        original = {"audio": self.audio.read_bytes(), "generation_record": self.record.read_bytes(),
                    "music_intent": self.intent.read_bytes()}
        code, result = self.call("candidate", "register", "--audio", self.audio,
                                 "--generation-record", self.record, "--intent", self.intent, "--request-id", "register")
        self.assertEqual(code, 0)
        self.assertEqual(result["audio_model_calls"], 0)
        self.assertEqual([item["role"] for item in result["outputs"]], list(original))
        self.assertEqual(len(result["playback"]), 1)
        audio = result["outputs"][0]
        self.assertEqual(result["playback"][0]["asset_id"], audio["asset_id"])
        for item in result["outputs"]:
            self.assertEqual(self.store.asset(item["asset_id"])[1], original[item["role"]])
            if item["role"] != "audio":
                self.assertEqual(item["parents"], [{"role": "describes", "asset_id": audio["asset_id"], "digest": audio["digest"]}])
                self.assertEqual(audio["provenance"]["attachments"][item["role"]], item["digest"])
        self.assertFalse((self.workspace / "sessions.sqlite3").exists())
        for path in (self.audio, self.record, self.intent):
            path.unlink()
        self.assertEqual(self.call("action", "show", "register"), (0, result))

    def test_mismatched_record_is_rejected_before_claim_and_can_be_corrected(self):
        for field, value in (("sha256", "sha256:" + "0" * 64), ("frame_count", 61), ("channels", 2)):
            with self.subTest(field=field):
                document = copy.deepcopy(self.record_document)
                target = document["output"] if field == "sha256" else document["output"]["media"]
                target[field] = value
                self.record.write_text(json.dumps(document), encoding="utf-8")
                with self.assertRaises(AudioError) as caught:
                    self.register()
                self.assertEqual(caught.exception.code, "generation_record_mismatch")
                self.assertFalse(self.workspace.exists())
        self.record.write_text(json.dumps(self.record_document), encoding="utf-8")
        self.assertEqual(self.register()["status"], "succeeded")

    def test_invalid_metadata_does_not_create_a_workspace(self):
        original_record, original_intent = self.record.read_bytes(), self.intent.read_bytes()
        cases = [(self.record, b'{"kind":1,"kind":2}', "invalid_json"),
                 (self.record, b'[]', "invalid_request"),
                 (self.intent, b'{"schema":"score-music-intent/v1","source":"agent","purpose":"x","approved":true}', "invalid_request"),
                 (self.intent, b'{"schema":"score-music-intent/v1","source":"agent","purpose":" "}', "invalid_request"),
                 (self.intent, b'{"purpose":NaN}', "invalid_json"),
                 (self.intent, b'x' * (1024 * 1024 + 1), "invalid_source")]
        for path, data, error in cases:
            with self.subTest(data=data[:70]):
                self.record.write_bytes(original_record)
                self.intent.write_bytes(original_intent)
                path.write_bytes(data)
                with self.assertRaises(AudioError) as caught:
                    self.register()
                self.assertEqual(caught.exception.code, error)
                self.assertFalse(self.workspace.exists())

    def test_replay_binds_content_and_relocated_inputs_not_their_current_paths(self):
        result = self.register()
        moved_audio, moved_record, moved_intent = [self.root / name for name in ("moved.wav", "moved-record.json", "moved-intent.json")]
        for source, target in ((self.audio, moved_audio), (self.record, moved_record), (self.intent, moved_intent)):
            source.rename(target)
        replayed = register_candidate(self.store, moved_audio, "register", generation_record=moved_record, intent=moved_intent)
        self.assertEqual(replayed, result)
        moved_intent.write_text(json.dumps({**self.intent_document, "purpose": "Changed intention"}), encoding="utf-8")
        with self.assertRaises(AudioError) as caught:
            register_candidate(self.store, moved_audio, "register", generation_record=moved_record, intent=moved_intent)
        self.assertEqual(caught.exception.code, "request_conflict")
        self.assertEqual(len(list((self.workspace / "objects").iterdir())), 1)

    def test_missing_record_does_not_invent_a_generation_origin(self):
        imported = self.register("plain", generation_record=None, intent=None)
        self.assertEqual(imported["binding"]["operation"], "import.wav/v1")
        self.assertEqual(imported["outputs"][0]["provenance"]["kind"], "local_import")
        self.assertEqual(imported["outputs"][0]["provenance"]["rights"], "unknown")
        annotated = self.register("annotated", generation_record=None)
        self.assertEqual([item["role"] for item in annotated["outputs"]], ["audio", "music_intent"])
        self.assertEqual(annotated["outputs"][0]["provenance"]["origin"], "unknown")
        self.assertEqual(annotated["findings"][0]["generation_record_binding"], "absent")

    def test_session_selection_is_explicit_revision_checked_and_not_feedback(self):
        first = self.register()["outputs"][0]["asset_id"]
        self.assertFalse((self.workspace / "sessions.sqlite3").exists())
        code, _ = self.mutation(["session", "create"], {"schema": "matter-session-create/v1", "request_id": "create",
            "session_id": "music", "name": "Fixture"})
        self.assertEqual(code, 0)
        self.assertIsNone(self.call("session", "show", "music")[1]["current"]["selected_asset"])
        select = {"schema": "matter-session-select/v1", "request_id": "select", "session_id": "music",
                  "expected_revision": 1, "asset_id": first}
        code, selected = self.mutation(["session", "select"], select)
        self.assertEqual(code, 0)
        self.assertEqual(self.mutation(["session", "select"], select), (0, selected))
        second = self.register("second")["outputs"][0]["asset_id"]
        code, context = self.call("context", "show", "music")
        self.assertEqual(context["current"]["selected_asset"]["asset_id"], first)
        self.assertEqual(context["feedback"], [])
        self.assertEqual(context["audio_model_calls"], 0)
        code, failed = self.mutation(["session", "select"], {**select, "request_id": "stale", "asset_id": second})
        self.assertEqual(code, 2)
        self.assertEqual(failed["error"]["code"], "revision_conflict")
        self.assertEqual(self.call("session", "show", "music")[1]["current"]["selected_asset"]["asset_id"], first)
        self.assertEqual(self.mutation(["session", "select"], {**select, "request_id": "new-selection",
                         "expected_revision": 2, "asset_id": second})[0], 0)

    def test_unpublished_claim_stays_pending_without_a_new_registration_or_generation(self):
        publish = self.store._publish

        def fail_result(target, files):
            if target.parent.name == "objects":
                raise OSError("Synthetic interrupted publication")
            return publish(target, files)

        with patch.object(self.store, "_publish", side_effect=fail_result), self.assertRaises(OSError):
            self.register()
        for operation in (lambda: self.store.show_request("register"), self.register):
            with self.assertRaises(AudioError) as caught:
                operation()
            self.assertEqual(caught.exception.code, "recovery_pending")
        self.assertEqual(list((self.workspace / "objects").iterdir()), [])
        self.assertEqual(len(list((self.workspace / "requests").iterdir())), 1)

    def test_attachment_integrity_is_checked_when_loading_its_audio(self):
        result = self.register()
        attachment = result["outputs"][1]
        (self.workspace / attachment["locator"]).write_bytes(b"changed attachment")
        with self.assertRaises(AudioError) as caught:
            self.store.asset(result["outputs"][0]["asset_id"])
        self.assertEqual(caught.exception.code, "integrity_error")


if __name__ == "__main__":
    unittest.main()
