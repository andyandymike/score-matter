"""Adapter mechanics use synthetic proposals; live SA3 checks are separate."""
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
    raise unittest.SkipTest("Install requirements-audio.txt for the optional SA3 adapter tests") from exc

from matter_audio_core.actions import ActionService, Registry
from matter_audio_core.artifacts import ArtifactStore
from matter_audio_core.contracts import request
from matter_audio_core.errors import AudioError
from matter_audio_core.media import PCM, decode_wav, encode_wav, sample_bytes
from matter_audio_core.processes import ProcessResult
from matter_audio_core.sessions import SessionService
from score_matter.authoring import SA3Runtime
from score_matter.sa3_edit import SA3EditAdapter, RATE


class InpaintAdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.adapter = SA3EditAdapter(self.root)
        self.runtime = SA3Runtime(self.root, self.root / "python", self.root / "driver.py")
        self.adapter.signature = lambda: (self.runtime, {"synthetic_fixture": True})
        self.pcm = PCM(sample_bytes(array("h", [100, -100] * (RATE + 100))), RATE, 2)
        self.parameters = {"prompt": "Synthetic test only", "start_frame": 12000, "end_frame": 30000, "seed": 7}
        self.store = ArtifactStore(self.root / "workspace", product="score-matter")
        source = self.root / "source.wav"
        source.write_bytes(encode_wav(self.pcm))
        self.asset = self.store.import_wav(source, "import")["outputs"][0]["asset_id"]
        registry = Registry()
        registry.register(self.adapter.operation())
        self.actions = ActionService(self.store, registry)

    def proposal(self, argv, **kwargs):
        self.assertNotIn("--play", argv)
        self.assertEqual(kwargs["environment"]["HF_HUB_OFFLINE"], "1")
        self.assertNotIn("OPENAI_API_KEY", kwargs["environment"])
        duration = int(argv[argv.index("--seconds") + 1])
        target = Path(argv[argv.index("--out") + 1])
        target.write_bytes(encode_wav(PCM(sample_bytes(array("h", [2000, -2000] * (duration * RATE))), RATE, 2)))
        return ProcessResult("", "", {"synthetic_fixture": True})

    def test_proposal_is_cropped_and_pasted_only_inside_the_write_window(self):
        action = request("edit", "score.sa3_inpaint/v1", self.asset, self.parameters)
        with patch("score_matter.sa3_edit.run_process", side_effect=self.proposal) as backend:
            result = self.actions.execute(action)
        self.assertEqual(backend.call_count, 1)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual([x["role"] for x in result["outputs"]], ["audio", "model_proposal"])
        output = decode_wav(self.store.asset(result["outputs"][0]["asset_id"])[1])
        self.assertEqual(output.frames, self.pcm.frames)
        self.assertEqual(output.payload[:12000 * 4], self.pcm.payload[:12000 * 4])
        self.assertEqual(output.payload[30000 * 4:], self.pcm.payload[30000 * 4:])
        report = result["findings"][0]
        self.assertEqual(report["observed_changes"]["outside_changed_sample_count"], 0)
        self.assertGreater(report["model_observed_changes"]["outside_changed_sample_count"], 0)
        self.assertEqual(report["output_adaptation"]["raw_frames"], RATE * 2)
        self.assertEqual(result["audio_model_calls"], 0)  # Mock creates PCM; it does not run SA3.

    def test_protected_edit_rejects_before_any_backend_launch(self):
        sessions = SessionService(self.store)
        sessions.mutate("create", {"schema": "matter-session-create/v1", "request_id": "create",
            "session_id": "music", "name": "Fixture", "asset_id": self.asset})
        sessions.mutate("constraints", {"schema": "matter-constraints-set/v1", "request_id": "protect",
            "session_id": "music", "expected_revision": 1, "regions": [{"start_frame": 0, "end_frame": 20000}]})
        action = {**request("edit", "score.sa3_inpaint/v1", self.asset, self.parameters), "protection": {"session_id": "music", "revision": 2}}
        with patch("score_matter.sa3_edit.run_process") as backend, self.assertRaises(AudioError) as caught:
            self.actions.execute(action)
        self.assertEqual(caught.exception.code, "constraint_violation")
        backend.assert_not_called()

    def test_tiny_mask_and_ignored_negative_prompt_are_rejected(self):
        for parameters, code in [({**self.parameters, "start_frame": 10000, "end_frame": 10001}, "model_mask_empty"),
                                 ({**self.parameters, "negative_prompt": "test", "cfg": 1}, "invalid_request")]:
            with self.assertRaises(AudioError) as caught:
                self.adapter.resolve(parameters, self.pcm)
            self.assertEqual(caught.exception.code, code)

    def test_runtime_change_and_bad_model_output_do_not_publish_audio(self):
        resolved = self.adapter.resolve(self.parameters, self.pcm)
        self.adapter.signature = lambda: (self.runtime, {"changed_fixture": True})
        with self.assertRaises(AudioError) as caught:
            self.adapter.execute(resolved, self.pcm)
        self.assertEqual(caught.exception.code, "runtime_changed")
        def bad(argv, **kwargs):
            Path(argv[argv.index("--out") + 1]).write_bytes(encode_wav(PCM(sample_bytes(array("h", [1] * RATE)), RATE, 1)))
            return ProcessResult("", "", {})
        with patch("score_matter.sa3_edit.run_process", side_effect=bad):
            result = self.actions.execute(request("bad", "score.sa3_inpaint/v1", self.asset, self.parameters))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["outputs"], [])
        self.assertEqual(result["error"]["code"], "sa3_output_mismatch")


if __name__ == "__main__":
    unittest.main()
