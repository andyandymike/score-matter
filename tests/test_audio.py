from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from array import array
from pathlib import Path

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
            root = Path(directory)
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
        code, response = self.call_with_core(SimpleNamespace(__version__="0.5.0"))
        self.assertEqual(code, 2)
        self.assertEqual(response["error"]["code"], "audio_dependency_incompatible")
        self.assertEqual(response["error"]["details"]["installed_core_version"], "0.5.0")

    def test_broken_core_dependency_is_not_reported_as_missing_core(self):
        with self.assertRaises(ModuleNotFoundError) as caught:
            self.call_with_core(ModuleNotFoundError("Broken dependency", name="broken_dependency"))
        self.assertEqual(caught.exception.name, "broken_dependency")
