from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from score_matter.authoring import (
    DEFAULT_RUNTIME_ROOT,
    REPOSITORY_ROOT,
    SA3GenerationSettings,
    SA3Runtime,
    build_sa3_command,
    generate_sa3_wav,
    resolve_sa3_runtime,
)
from score_matter.errors import BoundaryError, ProviderError
from score_matter.media import render_mock_sine_wav


class FastAuthoringTests(unittest.TestCase):
    @staticmethod
    def _runtime(root: Path) -> SA3Runtime:
        files = (
            root / ".venv" / "Scripts" / "python.exe",
            root / "scripts" / "sa3_tflite.py",
            root / "models" / "tokenizer.model",
            root / "models" / "tflite" / "sa3-m" / "dit_fp32.tflite",
            root / "models" / "tflite" / "same-l" / "dec_fp32.tflite",
            root / "models" / "tflite" / "t5gemma" / "encoder_fp16.tflite",
        )
        for path in files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")
        return resolve_sa3_runtime(root)

    def test_default_command_uses_the_known_medium_fast_path(self) -> None:
        runtime = SA3Runtime(
            root=Path("runtime"),
            python=Path("runtime/python.exe"),
            script=Path("runtime/sa3_tflite.py"),
        )
        command = build_sa3_command(
            runtime=runtime,
            prompt="Quiet star-map music",
            output=Path("candidate.wav"),
            settings=SA3GenerationSettings(),
            seed=1901,
        )

        self.assertEqual(command[0:2], [str(runtime.python), str(runtime.script)])
        self.assertIn("medium", command)
        self.assertIn("same-l", command)
        self.assertIn("fp32", command)
        self.assertEqual(command[command.index("--seconds") + 1], "20")
        self.assertEqual(command[command.index("--steps") + 1], "8")
        self.assertEqual(command[command.index("--threads") + 1], "8")
        self.assertEqual(command[command.index("--cfg") + 1], "1.0")
        self.assertIn("--free-models", command)
        self.assertNotIn("--negative-prompt", command)

    def test_generation_runs_once_and_returns_one_valid_wav(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self._runtime(root / "runtime")
            output = root / "candidate.wav"
            calls: list[list[str]] = []

            def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(command)
                self.assertEqual(kwargs["cwd"], runtime.root)
                self.assertFalse(kwargs["check"])
                environment = kwargs["env"]
                assert isinstance(environment, dict)
                self.assertEqual(environment["HF_HUB_OFFLINE"], "1")
                destination = Path(command[command.index("--out") + 1])
                seconds = int(command[command.index("--seconds") + 1])
                seed = int(command[command.index("--seed") + 1])
                render_mock_sine_wav(
                    destination,
                    sample_rate_hz=44100,
                    channels=2,
                    duration_samples=seconds * 44100,
                    frequency_hz=220.0,
                    amplitude=0.1,
                    seed=seed,
                )
                return subprocess.CompletedProcess(command, 0)

            score_local = root / "score-local"
            with (
                patch("score_matter.authoring.DEFAULT_OUTPUT_ROOT", score_local),
                patch("score_matter.authoring.subprocess.run", side_effect=fake_run),
            ):
                result = generate_sa3_wav(
                    "Warm restrained game BGM",
                    settings=SA3GenerationSettings(seconds=1, seed=2719),
                    output=output,
                    runtime_root=runtime.root,
                )

            self.assertEqual(len(calls), 1)
            self.assertEqual(result.path, output.resolve())
            self.assertEqual(result.media["sample_rate_hz"], 44100)
            self.assertEqual(result.media["channels"], 2)
            self.assertEqual(result.media["frame_count"], 44100)
            self.assertIsNone(result.record_warning)
            assert result.record_path is not None
            self.assertTrue(result.record_path.is_relative_to(score_local / "records"))
            self.assertFalse(output.with_suffix(".generation.json").exists())
            record = json.loads(result.record_path.read_text(encoding="utf-8"))
            self.assertEqual(record["status"], "candidate")
            self.assertEqual(record["attempt_count"], 1)
            self.assertEqual(record["automatic_retries"], 0)

    def test_default_output_stays_in_score_matter_when_called_from_consumer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self._runtime(root / "runtime")
            score_local = (root / "score-matter" / ".local" / "authoring").resolve()
            consumer = root / "judgement-horror"
            consumer.mkdir()

            def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                destination = Path(command[command.index("--out") + 1])
                render_mock_sine_wav(
                    destination,
                    sample_rate_hz=44100,
                    channels=2,
                    duration_samples=44100,
                    frequency_hz=220.0,
                    amplitude=0.1,
                    seed=2719,
                )
                return subprocess.CompletedProcess(command, 0)

            original_cwd = Path.cwd()
            try:
                os.chdir(consumer)
                with (
                    patch(
                        "score_matter.authoring.DEFAULT_OUTPUT_ROOT", score_local
                    ),
                    patch(
                        "score_matter.authoring.resolve_sa3_runtime",
                        return_value=runtime,
                    ),
                    patch(
                        "score_matter.authoring.subprocess.run", side_effect=fake_run
                    ),
                ):
                    result = generate_sa3_wav(
                        "Consumer project BGM",
                        settings=SA3GenerationSettings(seconds=1, seed=2719),
                    )
            finally:
                os.chdir(original_cwd)

            self.assertTrue(result.path.is_relative_to(score_local))
            self.assertFalse((consumer / ".local").exists())

    def test_default_runtime_is_anchored_to_the_score_matter_checkout(self) -> None:
        self.assertTrue(DEFAULT_RUNTIME_ROOT.is_absolute())
        self.assertEqual(
            DEFAULT_RUNTIME_ROOT,
            REPOSITORY_ROOT / "models" / "stable-audio-3" / "optimized" / "tflite",
        )

    def test_negative_prompt_with_cfg_one_fails_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            runtime = self._runtime(Path(temporary) / "runtime")
            with (
                patch("score_matter.authoring.subprocess.run") as run_mock,
                self.assertRaises(BoundaryError) as raised,
            ):
                generate_sa3_wav(
                    "Instrumental BGM",
                    settings=SA3GenerationSettings(negative_prompt="vocals"),
                    runtime_root=runtime.root,
                )
        self.assertEqual(raised.exception.code, "generation_settings_invalid")
        run_mock.assert_not_called()

    def test_existing_output_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self._runtime(root / "runtime")
            output = root / "candidate.wav"
            output.write_bytes(b"keep")
            with (
                patch("score_matter.authoring.subprocess.run") as run_mock,
                self.assertRaises(BoundaryError) as raised,
            ):
                generate_sa3_wav(
                    "Instrumental BGM",
                    output=output,
                    runtime_root=runtime.root,
                )
            self.assertEqual(output.read_bytes(), b"keep")
        self.assertEqual(raised.exception.code, "destination_exists")
        run_mock.assert_not_called()

    def test_missing_runtime_fails_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with (
                patch("score_matter.authoring.subprocess.run") as run_mock,
                self.assertRaises(ProviderError) as raised,
            ):
                generate_sa3_wav(
                    "Instrumental BGM",
                    runtime_root=Path(temporary) / "missing",
                )
        self.assertEqual(raised.exception.code, "sa3_runtime_unavailable")
        run_mock.assert_not_called()

    def test_wrong_audio_shape_is_rejected_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self._runtime(root / "runtime")

            def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                destination = Path(command[command.index("--out") + 1])
                render_mock_sine_wav(
                    destination,
                    sample_rate_hz=48000,
                    channels=2,
                    duration_samples=48000,
                    frequency_hz=220.0,
                    amplitude=0.1,
                    seed=1,
                )
                return subprocess.CompletedProcess(command, 0)

            with (
                patch(
                    "score_matter.authoring.subprocess.run", side_effect=fake_run
                ) as run_mock,
                self.assertRaises(ProviderError) as raised,
            ):
                generate_sa3_wav(
                    "Instrumental BGM",
                    settings=SA3GenerationSettings(seconds=1, seed=1),
                    output=root / "wrong.wav",
                    runtime_root=runtime.root,
                )
            self.assertFalse((root / "wrong.wav").exists())
            self.assertEqual(list(root.glob(".wrong.wav.*.tmp.wav")), [])
        self.assertEqual(raised.exception.code, "sa3_output_invalid")
        run_mock.assert_called_once()

    def test_timeout_is_reported_without_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self._runtime(root / "runtime")
            output = root / "timeout.wav"
            with (
                patch(
                    "score_matter.authoring.subprocess.run",
                    side_effect=subprocess.TimeoutExpired(["sa3"], 1),
                ) as run_mock,
                self.assertRaises(ProviderError) as raised,
            ):
                generate_sa3_wav(
                    "Instrumental BGM",
                    settings=SA3GenerationSettings(timeout_seconds=1),
                    output=output,
                    runtime_root=runtime.root,
                )
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".timeout.wav.*.tmp.wav")), [])
        self.assertEqual(raised.exception.code, "sa3_generation_timed_out")
        run_mock.assert_called_once()

    def test_failed_process_leaves_no_candidate_or_staging_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self._runtime(root / "runtime")
            output = root / "failed.wav"

            def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                Path(command[command.index("--out") + 1]).write_bytes(b"partial")
                return subprocess.CompletedProcess(command, 7)

            with (
                patch(
                    "score_matter.authoring.subprocess.run", side_effect=fake_run
                ) as run_mock,
                self.assertRaises(ProviderError) as raised,
            ):
                generate_sa3_wav(
                    "Instrumental BGM",
                    output=output,
                    runtime_root=runtime.root,
                )

            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".failed.wav.*.tmp.wav")), [])
        self.assertEqual(raised.exception.code, "sa3_generation_failed")
        run_mock.assert_called_once()

    def test_failed_default_attempt_removes_its_empty_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self._runtime(root / "runtime")
            output_root = root / "authoring"
            with (
                patch(
                    "score_matter.authoring.subprocess.run",
                    return_value=subprocess.CompletedProcess(["sa3"], 7),
                ) as run_mock,
                self.assertRaises(ProviderError) as raised,
            ):
                generate_sa3_wav(
                    "Instrumental BGM",
                    output_root=output_root,
                    runtime_root=runtime.root,
                )

            self.assertEqual(list(output_root.iterdir()), [])
        self.assertEqual(raised.exception.code, "sa3_generation_failed")
        run_mock.assert_called_once()

    def test_concurrent_destination_is_preserved_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self._runtime(root / "runtime")
            output = root / "candidate.wav"

            def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
                staging = Path(command[command.index("--out") + 1])
                render_mock_sine_wav(
                    staging,
                    sample_rate_hz=44100,
                    channels=2,
                    duration_samples=44100,
                    frequency_hz=220.0,
                    amplitude=0.1,
                    seed=1,
                )
                output.write_bytes(b"concurrent-writer")
                return subprocess.CompletedProcess(command, 0)

            with (
                patch(
                    "score_matter.authoring.subprocess.run", side_effect=fake_run
                ) as run_mock,
                self.assertRaises(BoundaryError) as raised,
            ):
                generate_sa3_wav(
                    "Instrumental BGM",
                    settings=SA3GenerationSettings(seconds=1, seed=1),
                    output=output,
                    runtime_root=runtime.root,
                )

            self.assertEqual(output.read_bytes(), b"concurrent-writer")
            self.assertEqual(list(root.glob(".candidate.wav.*.tmp.wav")), [])
        self.assertEqual(raised.exception.code, "destination_exists")
        run_mock.assert_called_once()

    def test_invalid_output_parent_is_a_clean_cli_boundary_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runtime = self._runtime(root / "runtime")
            parent_file = root / "not-a-directory"
            parent_file.write_bytes(b"fixture")
            with (
                patch("score_matter.authoring.subprocess.run") as run_mock,
                self.assertRaises(BoundaryError) as raised,
            ):
                generate_sa3_wav(
                    "Instrumental BGM",
                    output=parent_file / "candidate.wav",
                    runtime_root=runtime.root,
                )
        self.assertEqual(raised.exception.code, "generation_output_invalid")
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
