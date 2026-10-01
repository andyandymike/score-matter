from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

try:
    from matter_audio_core import __version__ as CORE_VERSION
    from matter_audio_core.media import PCM, encode_wav, sample_bytes
    CORE_AVAILABLE = True
except ModuleNotFoundError as exc:
    if exc.name != "matter_audio_core":
        raise
    CORE_AVAILABLE = False
from score_matter.cli import main


@unittest.skipUnless(CORE_AVAILABLE, "Install the optional audio dependency for shared authoring tests")
class SharedAudioTests(unittest.TestCase):
    def call(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(["audio", *args, "--json"])
        return code, json.loads(output.getvalue())

    def test_product_capabilities(self):
        code, result = self.call("capabilities")
        self.assertEqual(code, 0)
        self.assertEqual(result["product"], "score-matter")
        self.assertEqual(result["core_version"], CORE_VERSION)
        self.assertEqual(result["sessions"]["availability"], "available")

    def test_import_gain_and_query(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assert_import_gain_and_query(Path(directory))

    def assert_import_gain_and_query(self, root):
        source = root / "music.wav"
        source.write_bytes(encode_wav(PCM(sample_bytes(array("h", [-10000, 0, 10000] * 20)), 8000, 1)))
        original = source.read_bytes()
        workspace = ["--workspace", str(root / "workspace")]
        code, imported = self.call(*workspace, "assets", "import", str(source), "--request-id", "input")
        self.assertEqual(code, 0)
        path = root / "action.json"
        path.write_text(json.dumps({"schema": "matter-action/v1", "request_id": "quiet",
                                    "operation": "gain/v1", "inputs": [imported["outputs"][0]["asset_id"]],
                                    "parameters": {"db": -3}}))
        code, result = self.call(*workspace, "action", "execute", "--request", str(path))
        self.assertEqual(code, 0)
        self.assertEqual(result["audio_model_calls"], 0)
        self.assertTrue(Path(result["playback"][0]["path"]).is_file())
        self.assertEqual(self.call(*workspace, "action", "show", "quiet")[1], result)
        self.assertEqual(source.read_bytes(), original)

    def assert_unreadable_sa3_is_optional(self, driver_bytes, read_error=None):
        from matter_audio_core.errors import AudioError
        from score_matter.sa3_edit import COMPONENTS, SA3EditAdapter

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            runtime = root / "runtime"
            for name in (".venv/Scripts/python.exe", "scripts/sa3_tflite.py", *COMPONENTS):
                path = runtime / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            driver = runtime / "scripts/sa3_tflite.py"
            driver.write_bytes(driver_bytes)
            original_read_text = Path.read_text

            def read_text(path, *args, **kwargs):
                if path == driver and read_error is not None:
                    raise read_error
                return original_read_text(path, *args, **kwargs)

            with (
                patch.dict("os.environ", {"SCORE_MATTER_SA3_ROOT": str(runtime)}),
                patch.object(Path, "read_text", read_text),
                patch("score_matter.sa3_edit.run_process") as backend,
            ):
                code, capabilities = self.call("capabilities")
                self.assertEqual(code, 0)
                operations = {item["operation"]: item for item in capabilities["operations"]}
                self.assertEqual(operations["score.sa3_inpaint/v1"]["availability"], "unavailable")
                self.assertEqual(operations["gain/v1"]["availability"], "available")
                self.assert_import_gain_and_query(root)
                with self.assertRaises(AudioError) as caught:
                    SA3EditAdapter(runtime).signature()
                self.assertEqual(caught.exception.code, "sa3_driver_unavailable")
                backend.assert_not_called()

    def test_sa3_driver_decode_failure_keeps_pcm_available(self):
        self.assert_unreadable_sa3_is_optional(b"# coding: latin-1\n# \xe9\n")

    def test_sa3_driver_read_failure_keeps_pcm_available(self):
        self.assert_unreadable_sa3_is_optional(b"# fixture\n", PermissionError("Unreadable driver fixture"))


class AudioDependencyTests(unittest.TestCase):
    """The base installation must remain usable without the optional core."""

    def call_with_core(self, replacement):
        import builtins
        from unittest.mock import patch
        original_import = builtins.__import__

        def substitute(name, *args, **kwargs):
            if name == "matter_audio_core":
                if isinstance(replacement, Exception):
                    raise replacement
                return replacement
            return original_import(name, *args, **kwargs)

        output = io.StringIO()
        with patch("builtins.__import__", side_effect=substitute), contextlib.redirect_stdout(output):
            code = main(["audio", "capabilities", "--json"])
        return code, json.loads(output.getvalue())

    def test_missing_optional_core_has_an_installation_error(self):
        code, response = self.call_with_core(ModuleNotFoundError("No core installed", name="matter_audio_core"))
        self.assertEqual(code, 2)
        self.assertEqual(response["error"]["code"], "audio_dependency_missing")

    def test_old_optional_core_is_rejected_before_loading_adapters(self):
        from types import SimpleNamespace
        for version in ("0.5.0", "0.6.0"):
            with self.subTest(version=version):
                code, response = self.call_with_core(SimpleNamespace(__version__=version))
                self.assertEqual(code, 2)
                self.assertEqual(response["error"]["code"], "audio_dependency_incompatible")
                self.assertEqual(response["error"]["details"]["installed_core_version"], version)
                self.assertEqual(response["error"]["details"]["required_core_version"], "0.6.1")

    def test_broken_core_dependency_is_not_reported_as_missing_core(self):
        with self.assertRaises(ModuleNotFoundError) as caught:
            self.call_with_core(ModuleNotFoundError("Broken dependency", name="broken_dependency"))
        self.assertEqual(caught.exception.name, "broken_dependency")
