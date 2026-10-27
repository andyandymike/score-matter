"""Doctor only reads bounded local facts; it cannot load or execute SA3."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from matter_audio_core.diagnostics import build_report
except ModuleNotFoundError as exc:
    if exc.name not in ("matter_audio_core", "matter_audio_core.diagnostics"):
        raise
    raise unittest.SkipTest("Optional current Core diagnostics required") from exc

from score_matter.diagnostics import doctor_provider
from score_matter.sa3_edit import COMPONENTS


class ScoreDoctorTests(unittest.TestCase):
    def diagnose(self, root):
        with patch.dict("os.environ", {"SCORE_MATTER_SA3_ROOT": str(root), "PRIVATE_TEST_TOKEN": "do-not-return"}), \
             patch("subprocess.run", side_effect=AssertionError("executed")), \
             patch("subprocess.Popen", side_effect=AssertionError("spawned")), \
             patch("score_matter.sa3_edit.run_process", side_effect=AssertionError("model called")):
            report = build_report("score-matter", doctor_provider())
        rendered = json.dumps(report)
        self.assertNotIn(str(root), rendered)
        self.assertNotIn("do-not-return", rendered)
        backend = report["backends"][0]
        self.assertEqual(backend["loaded"], "unknown")
        self.assertEqual(backend["execution_device"], "unknown")
        return backend

    def fixture(self, root):
        for name in (".venv/Scripts/python.exe", *COMPONENTS):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"not executable model-free fixture")
        script = root / "scripts/sa3_tflite.py"
        script.parent.mkdir(parents=True)
        script.write_text("\n".join(("SAMPLE_RATE=44100", "SAMPLES_PER_LATENT=4096",
                                   "int(round(inp_start_sec*SAMPLE_RATE/SAMPLES_PER_LATENT))",
                                   "int(round(inp_end_sec*SAMPLE_RATE/SAMPLES_PER_LATENT))",
                                   "int(np.ceil(seconds*SAMPLE_RATE/SAMPLES_PER_LATENT))")), encoding="utf-8")
        return script

    def test_missing_runtime_is_unavailable_without_exposing_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.diagnose(Path(directory) / "private-location")["availability"], "unavailable")

    def test_static_readiness_does_not_claim_runtime_or_device_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            report = self.diagnose(root)
            self.assertEqual(report["availability"], "available")
            checks = {item["id"]: item for item in report["checks"]}
            self.assertEqual(len(checks["sa3_configuration"]["details"]["configuration_id"]), 64)
            (root / COMPONENTS[3]).write_bytes(b"")
            self.assertEqual(self.diagnose(root)["availability"], "unavailable")

    def test_invalid_utf8_and_oversized_driver_are_bounded_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = self.fixture(root)
            for data in (b"\xff", b"#" * (256 * 1024 + 1)):
                script.write_bytes(data)
                self.assertEqual(self.diagnose(root)["availability"], "unavailable")

    def test_present_default_runtime_counts_as_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            with patch.dict("os.environ", {"SCORE_MATTER_SA3_ROOT": ""}), \
                 patch("score_matter.diagnostics.DEFAULT_RUNTIME_ROOT", root), \
                 patch("subprocess.Popen", side_effect=AssertionError("spawned")):
                backend = doctor_provider()[0]
            self.assertTrue(backend["configured"])
            self.assertEqual(backend["availability"], "available")
            self.assertFalse(backend["checks"][0]["details"]["explicit_configuration"])

    def test_unreadable_component_returns_safe_error_without_duplicate_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            self.fixture(root)
            original_stat = Path.stat
            def stat(path, *args, **kwargs):
                if path == root / COMPONENTS[0]:
                    raise PermissionError("private-file-access-error")
                return original_stat(path, *args, **kwargs)
            with patch.object(Path, "stat", stat):
                backend = self.diagnose(root)
            self.assertEqual(backend["availability"], "unavailable")
            self.assertNotIn("private-file-access-error", json.dumps(backend))

    def test_actual_cli_succeeds_without_runtime_or_workspace(self):
        import matter_audio_core
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(root / "src"), str(Path(matter_audio_core.__file__).resolve().parents[1])]),
                   "SCORE_MATTER_SA3_ROOT": str(Path(directory) / "missing")}
            completed = subprocess.run([sys.executable, "-m", "score_matter", "audio", "doctor", "--json"],
                                       cwd=directory, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual(result["core"]["availability"], "available")
            self.assertEqual(result["backends"][0]["availability"], "unavailable")
            self.assertEqual(result["scope"]["subprocesses"], 0)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
