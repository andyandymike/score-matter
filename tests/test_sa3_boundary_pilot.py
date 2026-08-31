from __future__ import annotations

import array
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path

from score_matter.errors import BoundaryError
from score_matter.media import render_mock_sine_wav
from tools.sa3_boundary_pilot import (
    _closed_phase_review_candidates,
    _require_phase_gate,
    _windows_process_tree_working_set,
    analyze_edit_relationship,
    analyze_pcm16_wav,
    build_command,
    prepare_tail_input,
    repeat_wav,
    rms_match_copy,
    validate_plan,
)


def _attempt(attempt_id: str, phase: str) -> dict[str, object]:
    return {
        "id": attempt_id,
        "phase": phase,
        "family": "test-family",
        "kind": "text_to_audio",
        "prompt": "TrackType: Music, VocalType: Instrumental. A sparse test tone.",
        "seed": 1901,
        "seconds": 20,
        "cfg": 1.0,
    }


def _plan() -> dict[str, object]:
    attempts = [_attempt("cal-001", "calibration")]
    attempts.extend(_attempt(f"b{index:02d}", "phase1a") for index in range(1, 19))
    return {
        "schema": "score-sa3-boundary-plan/v1",
        "experiment_id": "test-pilot-v0",
        "status": "frozen",
        "spec": {
            "path": "spec/test.md",
            "sha256": "sha256:" + "0" * 64,
        },
        "runtime": {
            "source_root": "models/source",
            "source_commit": "0" * 40,
            "sa3_root": "models/source/optimized/tflite",
            "python": "models/source/optimized/tflite/.venv/Scripts/python.exe",
            "script": "models/source/optimized/tflite/scripts/sa3_tflite.py",
            "components": [
                {
                    "path": "models/source/optimized/tflite/models/tokenizer.model",
                    "bytes": 10,
                    "sha256": "sha256:" + "1" * 64,
                }
            ],
        },
        "terms": {
            "intended_use": "local_internal_evaluation",
            "review_state": "accepted_for_local_evaluation_only",
            "review_basis": "test fixture only",
            "sources": [
                {
                    "name": "fixture terms",
                    "url": "https://example.invalid/terms",
                    "observed_revision": "fixture",
                    "retrieved_on": "2026-08-28",
                    "snapshot_path": "models/stable-audio-3/LICENSE",
                    "sha256": "sha256:" + "2" * 64,
                }
            ],
        },
        "execution": {
            "experiment_root": ".local/experiments/test-pilot-v0",
            "dit": "medium",
            "decoder": "same-l",
            "precision": "fp32",
            "steps": 8,
            "threads": 8,
            "free_models": True,
            "calibration_timeout_seconds": 300,
            "attempt_timeout_seconds": 600,
            "minimum_free_bytes": 1,
            "offline_environment": {"HF_HUB_OFFLINE": "1"},
        },
        "review": {
            "blind_seed": 20260828,
            "target_rms_dbfs": -20.0,
            "sample_peak_ceiling_dbfs": -1.0,
            "loop_repeats": 8,
        },
        "attempts": attempts,
    }


class Sa3BoundaryPlanTests(unittest.TestCase):
    def _write_plan(self, root: Path, plan: dict[str, object]) -> Path:
        path = root / "plan.json"
        path.write_text(json.dumps(plan), encoding="utf-8")
        return path

    def test_exact_plan_shape_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            validated = validate_plan(self._write_plan(root, _plan()), repo=root)
        self.assertEqual(validated.document["experiment_id"], "test-pilot-v0")
        self.assertEqual(len(validated.attempts), 19)

    def test_unknown_field_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = _plan()
            plan["surprise"] = True
            with self.assertRaises(BoundaryError) as raised:
                validate_plan(self._write_plan(root, plan), repo=root)
        self.assertEqual(raised.exception.code, "pilot_plan_invalid")

    def test_negative_prompt_with_cfg_one_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = _plan()
            attempts = plan["attempts"]
            assert isinstance(attempts, list)
            attempts[1] = copy.deepcopy(attempts[1])
            attempts[1]["negative_prompt"] = "vocals"
            with self.assertRaises(BoundaryError) as raised:
                validate_plan(self._write_plan(root, plan), repo=root)
        self.assertEqual(raised.exception.code, "pilot_plan_invalid")

    def test_command_keeps_negative_attribution_parameters_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan_document = _plan()
            attempts = plan_document["attempts"]
            assert isinstance(attempts, list)
            attempts[1] = {
                **attempts[1],
                "cfg": 3.0,
                "apg": 1.0,
                "negative_prompt": "vocals, harsh resonance",
            }
            validated = validate_plan(self._write_plan(root, plan_document), repo=root)
            command = build_command(
                validated,
                validated.attempts["b01"],
                root / "output.wav",
                input_audio=None,
            )
        self.assertIn("--negative-prompt", command)
        self.assertEqual(command[command.index("--cfg") + 1], "3.0")
        self.assertEqual(command[command.index("--apg") + 1], "1.0")
        self.assertIn("--free-models", command)

    def test_phase1a_requires_successful_calibration_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            validated = validate_plan(self._write_plan(root, _plan()), repo=root)
            with self.assertRaises(BoundaryError) as raised:
                _require_phase_gate(validated, validated.attempts["b01"])
            status_path = (
                validated.experiment_root / "attempts" / "cal-001" / "status.json"
            )
            status_path.parent.mkdir(parents=True)
            status_path.write_text(
                json.dumps({"state": "complete", "wall_seconds": 50.0}),
                encoding="utf-8",
            )
            _require_phase_gate(validated, validated.attempts["b01"])
        self.assertEqual(raised.exception.code, "pilot_calibration_gate")

    def test_phase1b_is_not_authorized_by_frozen_pilot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            validated = validate_plan(self._write_plan(root, _plan()), repo=root)
            with self.assertRaises(BoundaryError) as raised:
                _require_phase_gate(validated, {"phase": "phase1b"})
        self.assertEqual(raised.exception.code, "pilot_phase_not_authorized")

    def test_closed_review_inventory_rejects_cherry_picked_subset(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan_document = _plan()
            attempts = plan_document["attempts"]
            assert isinstance(attempts, list)
            for attempt in attempts:
                attempt["seconds"] = 1
            validated = validate_plan(self._write_plan(root, plan_document), repo=root)
            phase_ids = []
            for attempt in attempts:
                if attempt["phase"] != "phase1a":
                    continue
                attempt_id = str(attempt["id"])
                phase_ids.append(attempt_id)
                attempt_root = validated.experiment_root / "attempts" / attempt_id
                attempt_root.mkdir(parents=True)
                raw = attempt_root / "raw.wav"
                render_mock_sine_wav(
                    raw,
                    sample_rate_hz=44100,
                    channels=2,
                    duration_samples=44100,
                    frequency_hz=330,
                    amplitude=0.1,
                    seed=7,
                )
                digest = analyze_pcm16_wav(raw)["file_sha256"]
                (attempt_root / "generation-record.json").write_text(
                    json.dumps({"output_sha256": digest}), encoding="utf-8"
                )
                (attempt_root / "status.json").write_text(
                    json.dumps({"state": "complete", "output_sha256": digest}),
                    encoding="utf-8",
                )
            phase, candidates = _closed_phase_review_candidates(validated, phase_ids)
            with self.assertRaises(BoundaryError) as raised:
                _closed_phase_review_candidates(validated, phase_ids[:-1])
        self.assertEqual(phase, "phase1a")
        self.assertEqual(len(candidates), 18)
        self.assertEqual(raised.exception.code, "pilot_review_blocked")


class Sa3BoundaryAudioTests(unittest.TestCase):
    def _audio(self, root: Path, *, amplitude: float = 0.1) -> Path:
        path = root / "source.wav"
        render_mock_sine_wav(
            path,
            sample_rate_hz=44100,
            channels=2,
            duration_samples=44100,
            frequency_hz=330,
            amplitude=amplitude,
            seed=7,
        )
        return path

    def test_pcm_analysis_checks_exact_media_and_signal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            analysis = analyze_pcm16_wav(self._audio(Path(temporary)), expected_seconds=1)
        self.assertTrue(analysis["hard_pass"])
        self.assertEqual(analysis["frame_count"], 44100)
        self.assertEqual(analysis["channels"], 2)
        self.assertLess(analysis["rms_dbfs"], 0)
        self.assertEqual(analysis["unavailable"][0], "true_peak_dbtp")

    def test_wrong_expected_duration_is_a_hard_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            analysis = analyze_pcm16_wav(self._audio(Path(temporary)), expected_seconds=2)
        self.assertFalse(analysis["hard_pass"])
        self.assertIn("wrong_frame_count", analysis["hard_failures"])

    def test_tail_padding_preserves_parent_and_adds_exact_zero_frames(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._audio(root)
            target = root / "tail.wav"
            record = prepare_tail_input(source, target, seconds=2)
            analysis = analyze_pcm16_wav(target, expected_seconds=2)
        self.assertTrue(analysis["hard_pass"])
        self.assertEqual(record["zero_padded_frames"], 44100)

    def test_rms_copy_is_derived_and_peak_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._audio(root, amplitude=0.01)
            target = root / "matched.wav"
            record = rms_match_copy(
                source,
                target,
                target_rms_dbfs=-20.0,
                peak_ceiling_dbfs=-1.0,
            )
        self.assertNotEqual(record["source_sha256"], record["output_sha256"])
        self.assertLessEqual(record["observed_output_sample_peak_dbfs"], -0.99)
        self.assertEqual(record["algorithm"], "linear_pcm16_rms_match_v1")

    def test_repeat_preview_has_no_seamless_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._audio(root)
            target = root / "repeat.wav"
            record = repeat_wav(source, target, repeats=4)
            analysis = analyze_pcm16_wav(target, expected_seconds=4)
        self.assertTrue(analysis["hard_pass"])
        self.assertFalse(record["crossfade_applied"])
        self.assertFalse(record["seamless_claim"])

    def test_edit_analysis_separates_inside_outside_and_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self._audio(root)
            child = root / "child.wav"
            with wave.open(str(source), "rb") as reader:
                payload = reader.readframes(reader.getnframes())
            samples = array.array("h")
            samples.frombytes(payload)
            for frame in range(11025, 33075):
                samples[frame * 2] = 0
                samples[frame * 2 + 1] = 0
            with wave.open(str(child), "wb") as writer:
                writer.setnchannels(2)
                writer.setsampwidth(2)
                writer.setframerate(44100)
                writer.writeframes(samples.tobytes())
            result = analyze_edit_relationship(
                source,
                child,
                inpaint_range_seconds=[0.25, 0.75],
            )
        self.assertTrue(result["regions"]["outside"]["bit_exact"])
        self.assertGreater(result["regions"]["inside"]["changed_sample_ratio"], 0.99)
        self.assertEqual(len(result["boundaries"]), 2)


class Sa3BoundaryResourceTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Windows process-tree measurement")
    def test_windows_measurement_follows_venv_launcher_children(self) -> None:
        child_code = (
            "import time;"
            "payload=bytearray(64*1024*1024);"
            "[payload.__setitem__(index,1) "
            "for index in range(0,len(payload),4096)];"
            "time.sleep(5)"
        )
        process = subprocess.Popen([sys.executable, "-c", child_code])
        try:
            time.sleep(1)
            observed = _windows_process_tree_working_set(process.pid)
        finally:
            process.terminate()
            process.wait(timeout=5)
        self.assertIsNotNone(observed)
        assert observed is not None
        self.assertGreater(observed, 48 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
