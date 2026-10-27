"""Synthetic original receipts and real PCM/CLI checks; never launch SA3."""
import copy
import json
import os
import subprocess
import sys
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
    raise unittest.SkipTest("Optional Core is required for proposal reassembly") from exc

from matter_audio_core.actions import ActionService, Registry
from matter_audio_core.artifacts import ArtifactStore
from matter_audio_core.contracts import canonical, fingerprint, request
from matter_audio_core.errors import AudioError
from matter_audio_core.media import PCM, decode_wav, encode_wav, sample_bytes
from matter_audio_core.processes import ProcessResult
from matter_audio_core.sessions import SessionService
from score_matter.authoring import SA3Runtime
from score_matter import proposals
from score_matter.sa3_edit import RATE, SA3EditAdapter


class ProposalReassemblyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = ArtifactStore(self.root / "workspace", product="score-matter")
        self.base = PCM(sample_bytes(array("h", [100, -100] * RATE)), RATE, 2)
        self.proposal = PCM(sample_bytes(array("h", [sample for frame in range(RATE)
                                                   for sample in (2000 + frame % 97, -2000 - frame % 97)])), RATE, 2)
        self.source = self.root / "source.wav"
        self.source.write_bytes(encode_wav(self.base))
        self.asset = self.store.import_wav(self.source, "import")["outputs"][0]["asset_id"]
        adapter = SA3EditAdapter(self.root)
        adapter.signature = lambda: (SA3Runtime(self.root, self.root / "python", self.root / "driver.py"), {"synthetic_fixture": True})
        registry = Registry()
        registry.register(adapter.operation())
        self.actions = ActionService(self.store, registry)
        self.original = request("generation", "score.sa3_inpaint/v1", self.asset,
                                {"prompt": "Synthetic fixture only", "seed": 7, "start_frame": 8192, "end_frame": 24576})
        with patch("score_matter.sa3_edit.run_process", side_effect=self.synthetic_process) as backend:
            self.generated = self.actions.execute(self.original)
        self.assertEqual(backend.call_count, 1)  # Fake writes PCM; no process/model ran.
        self.assertEqual(self.generated["status"], "succeeded")
        self.request = {"schema": "score-sa3-reassembly/v1", "request_id": "reuse", "source_request_id": "generation",
                        "base_asset_id": self.asset, "proposal_asset_id": self.generated["outputs"][1]["asset_id"],
                        "assembly": {"transition_frames": 4}}

    def synthetic_process(self, argv, **kwargs):
        Path(argv[argv.index("--out") + 1]).write_bytes(encode_wav(self.proposal))
        return ProcessResult("", "", {"synthetic_fixture": True})

    def plan_id(self, document=None):
        return proposals.plan(self.store, document or self.request)["plan"]["asset_id"]

    def assert_error(self, code, fn, *args):
        with self.assertRaises(AudioError) as caught:
            fn(*args)
        self.assertEqual(caught.exception.code, code)

    def absent(self, request_id):
        self.assert_error("request_not_found", self.store.show_request, request_id)

    def test_transition_plan_execute_and_replay_never_load_or_run_backend(self):
        before = self.source.read_bytes()
        with patch("score_matter.sa3_edit.run_process", side_effect=AssertionError("model called")), \
             patch.object(SA3EditAdapter, "signature", side_effect=AssertionError("runtime consulted")):
            saved = proposals.plan(self.store, self.request)
            plan_id = saved["plan"]["asset_id"]
            self.assertEqual(saved, proposals.plan(self.store, self.request))
            shown = proposals.show(self.store, plan_id)
            self.assertEqual(shown["document"]["reuse"]["new_model_inferences"], 0)
            result = proposals.execute(self.store, plan_id)
            self.assertEqual(result, proposals.execute(self.store, plan_id))
            self.assertEqual(result["audio_model_calls"], 0)
            self.assertEqual(result["new_model_inferences"], 0)
        output = decode_wav(self.store.asset(result["outputs"][0]["asset_id"])[1])
        expected = array("h", [100, -100] * RATE)
        # Independent 4-frame linear blend, exact Q24 rounding.
        scale = 1 << 24
        for frame in range(8192, 24576):
            distance = min(frame - 8192, 24575 - frame)
            weight = (scale * distance + 1) // 3 if distance < 4 else scale
            sample = (100 * (scale - weight) + (2000 + frame % 97) * weight + scale // 2) // scale
            expected[2 * frame], expected[2 * frame + 1] = sample, -sample
        self.assertEqual(output.payload, sample_bytes(expected))
        self.assertEqual(before, self.source.read_bytes())
        self.assertEqual(self.store.asset(self.asset)[1], before)
        self.assertFalse(any(self.store.root.glob("*.sqlite*")))

    def test_narrow_window_is_same_absolute_proposal_coordinates(self):
        self.request["assembly"] = {"start_frame": 10000, "end_frame": 12000, "transition_frames": 0}
        result = proposals.execute(self.store, self.plan_id())
        output = decode_wav(self.store.asset(result["outputs"][0]["asset_id"])[1])
        self.assertEqual(output.payload[:40000], self.base.payload[:40000])
        self.assertEqual(output.payload[40000:48000], self.proposal.payload[40000:48000])
        self.assertEqual(output.payload[48000:], self.base.payload[48000:])
        self.request.update(request_id="outside", assembly={"start_frame": 8000, "end_frame": 12000, "transition_frames": 0})
        self.assert_error("proposal_write_range", proposals.plan, self.store, self.request)
        self.absent("outside")

    def test_changed_generation_settings_and_request_conflicts(self):
        self.plan_id()
        for key in ("prompt", "seed", "steps", "model_mask"):
            changed = {**self.request, key: 7}
            self.assert_error("invalid_request", proposals.plan, self.store, changed)
        self.request["assembly"] = {"transition_frames": 0}
        self.assert_error("request_conflict", proposals.plan, self.store, self.request)

    def test_equal_pcm_wrong_base_or_proposal_identity_is_rejected(self):
        other_base = self.store.import_wav(self.source, "duplicate")["outputs"][0]["asset_id"]
        self.assert_error("proposal_source_mismatch", proposals.plan, self.store, {**self.request, "base_asset_id": other_base})
        with patch("score_matter.sa3_edit.run_process", side_effect=self.synthetic_process):
            other = self.actions.execute({**self.original, "request_id": "other-generation"})
        self.assertEqual(other["outputs"][1]["digest"], self.generated["outputs"][1]["digest"])
        self.assert_error("proposal_source_mismatch", proposals.plan, self.store,
                          {**self.request, "proposal_asset_id": other["outputs"][1]["asset_id"]})
        self.assert_error("proposal_source_mismatch", proposals.plan, self.store,
                          {**self.request, "proposal_asset_id": self.generated["outputs"][0]["asset_id"]})
        self.absent("reuse")

    def test_malformed_or_forged_recorded_generation_is_rejected(self):
        for change in ("effective", "finding", "final"):
            bad = copy.deepcopy(self.generated)
            if change == "effective":
                bad["resolution"]["effective_parameters"]["seed"] += 1
                body = {k: v for k, v in bad["resolution"].items() if k != "digest"}
                bad["resolution"]["digest"] = fingerprint(body)
                bad["binding"]["resolution"] = bad["resolution"]
                bad["binding_digest"] = fingerprint(bad["binding"])
            elif change == "finding":
                bad["findings"][0]["allowed_write"][0]["start_frame"] = 0
            else:
                bad["outputs"][0]["parents"] = []
            with patch.object(self.store, "show_request", return_value=bad):
                self.assert_error("proposal_source_mismatch", proposals.plan, self.store, self.request)
        self.absent("reuse")

    def session(self):
        service = SessionService(self.store)
        service.mutate("create", {"schema": "matter-session-create/v1", "request_id": "session-create",
                                  "session_id": "music", "name": "Fixture", "asset_id": self.asset})
        return service

    def lock(self, service, revision, start, end, request_id):
        return service.mutate("constraints", {"schema": "matter-constraints-set/v1", "request_id": request_id,
                              "session_id": "music", "expected_revision": revision,
                              "regions": [{"start_frame": start, "end_frame": end}]})

    def test_protection_preflight_changed_locks_and_completed_replay(self):
        service = self.session()
        self.lock(service, 1, 0, 8000, "first-lock")
        self.request["protection"] = {"session_id": "music", "revision": 2}
        saved = proposals.plan(self.store, self.request)
        completed = proposals.execute(self.store, saved["plan"]["asset_id"])
        pending = proposals.plan(self.store, {**self.request, "request_id": "not-yet-executed"})
        self.lock(service, 2, 9000, 10000, "new-lock")
        self.assertEqual(completed, proposals.execute(self.store, saved["plan"]["asset_id"]))
        self.assertEqual(saved, proposals.plan(self.store, self.request))
        self.assert_error("constraint_conflict", proposals.execute, self.store, pending["plan"]["asset_id"])
        self.absent(pending["document"]["core_request"]["request_id"])
        blocked = {**self.request, "request_id": "blocked", "protection": {"session_id": "music", "revision": 3}}
        self.assert_error("constraint_violation", proposals.plan, self.store, blocked)
        self.absent("blocked")

    def test_original_protection_is_retained_without_override(self):
        service = self.session()
        self.lock(service, 1, 0, 8000, "first-lock")
        original = {**self.original, "request_id": "protected-generation", "protection": {"session_id": "music", "revision": 2}}
        with patch("score_matter.sa3_edit.run_process", side_effect=self.synthetic_process):
            generated = self.actions.execute(original)
        self.request.update(source_request_id="protected-generation", proposal_asset_id=generated["outputs"][1]["asset_id"])
        saved = proposals.plan(self.store, self.request)
        self.assertEqual(saved["document"]["core_request"]["protection"], original["protection"])
        self.lock(service, 2, 9000, 10000, "new-lock")
        self.assert_error("constraint_conflict", proposals.execute, self.store, saved["plan"]["asset_id"])

    def test_claims_stay_pending_without_regenerating(self):
        def interrupt(publication):
            raise KeyboardInterrupt("simulated interrupted publication")
        with self.assertRaises(KeyboardInterrupt):
            self.store.transact("reuse", proposals._binding(self.store, self.request), interrupt)
        self.assert_error("recovery_pending", proposals.plan, self.store, self.request)
        saved = proposals.plan(self.store, {**self.request, "request_id": "another-plan"})
        doc = saved["document"]
        with self.assertRaises(KeyboardInterrupt):
            self.store.transact(doc["core_request"]["request_id"], {"resolution": doc["core_resolution"]}, interrupt)
        self.assert_error("recovery_pending", proposals.execute, self.store, saved["plan"]["asset_id"])

    def test_failed_or_unfinished_generation_is_not_a_reusable_source(self):
        def fail(publication):
            raise AudioError("synthetic_failure", "No model was run")
        def interrupt(publication):
            raise KeyboardInterrupt("simulated incomplete generation receipt")
        self.store.transact("failed-generation", {}, fail)
        with self.assertRaises(KeyboardInterrupt):
            self.store.transact("pending-generation", {}, interrupt)
        with patch("score_matter.sa3_edit.run_process", side_effect=AssertionError("retried model")):
            self.assert_error("proposal_source_mismatch", proposals.plan, self.store,
                              {**self.request, "source_request_id": "failed-generation"})
            self.assert_error("recovery_pending", proposals.plan, self.store,
                              {**self.request, "source_request_id": "pending-generation"})
        self.absent("reuse")

    def test_forged_saved_plan_cannot_change_assembly(self):
        saved = proposals.plan(self.store, self.request)
        document = copy.deepcopy(saved["document"])
        document["core_request"]["parameters"]["start_frame"] = 1
        def publish(publication):
            publication.add(canonical(document), {"content_type": "application/json"}, role="sa3_reassembly_plan")
            return {}
        forged = self.store.transact("forged", {}, publish)["outputs"][0]["asset_id"]
        self.assert_error("proposal_binding_mismatch", proposals.execute, self.store, forged)
        self.absent(saved["document"]["core_request"]["request_id"])

    def test_valid_document_cannot_hide_or_substitute_plan_asset_lineage(self):
        saved = proposals.plan(self.store, self.request)
        document, original_record = saved["document"], saved["plan"]
        variants = [(original_record["media"], []),
                    ({"content_type": "application/json"}, original_record["parents"]),
                    (original_record["media"], list(reversed(original_record["parents"])))]
        for index, (media, parents) in enumerate(variants):
            def publish(publication):
                publication.add(canonical(document), media, role="sa3_reassembly_plan", parents=parents)
                return {}
            forged = self.store.transact(f"forged-lineage-{index}", {}, publish)["outputs"][0]["asset_id"]
            self.assert_error("proposal_binding_mismatch", proposals.show, self.store, forged)
            self.assert_error("proposal_binding_mismatch", proposals.execute, self.store, forged)
        self.absent(saved["document"]["core_request"]["request_id"])

    def test_actual_cli_in_fresh_process_without_a_model_runtime(self):
        root = Path(__file__).resolve().parents[1]
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(root / "src"), str(Path(matter_audio_core.__file__).resolve().parents[1])]),
               "SCORE_MATTER_SA3_ROOT": str(self.root / "missing-runtime")}
        source = self.root / "request.json"
        source.write_text(json.dumps(self.request), encoding="utf-8")
        def call(*args):
            completed = subprocess.run([sys.executable, "-m", "score_matter", "audio", "--workspace", str(self.store.root),
                                        "proposal", *args, "--json"], cwd=self.root, env=env, capture_output=True, text=True, timeout=60)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            return json.loads(completed.stdout)
        saved = call("plan", "--request", str(source))
        asset_id = saved["plan"]["asset_id"]
        self.assertEqual(call("show", asset_id)["document"], saved["document"])
        result = call("execute", asset_id)
        self.assertEqual(result, call("execute", asset_id))
        self.assertEqual(result["audio_model_calls"], 0)
        self.assertEqual(len(result["playback"]), 1)
        self.assertTrue(Path(result["playback"][0]["path"]).is_file())


if __name__ == "__main__":
    unittest.main()
