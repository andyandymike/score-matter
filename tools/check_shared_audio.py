"""Verify installed product CLIs and adapter tests without models or playback."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
import sys
import tempfile
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCT = "score-matter"
ENTRY = ['score_matter', 'audio']


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    require(importlib.metadata.version("matter-audio-core") == "0.6.0", "Install the pinned core 0.6.0")
    if PRODUCT == "score-matter":
        requirements = importlib.metadata.requires("score-matter") or []
        require(any("matter-audio-core" in item and "audio" in item for item in requirements),
                "Reinstall ScoreMatter to refresh its audio extra metadata")
    else:
        require(importlib.metadata.version("miniaudio") == "1.71", "Install the pinned recording decoder")

    sys.path.insert(0, str(ROOT))
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for directory, pattern in [('tests', 'test_audio.py'), ('tests', 'test_sa3_edit.py')]:
        suite.addTests(loader.discover(str(ROOT / directory), pattern=pattern))
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    require(outcome.wasSuccessful() and not outcome.skipped, "Shared audio tests must pass without skips")

    with tempfile.TemporaryDirectory(prefix="matter-product-check-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        calls = 0

        def call(*arguments):
            nonlocal calls
            result = subprocess.run([sys.executable, "-m", *ENTRY, "--workspace", str(workspace),
                                     *map(str, arguments), "--json"], cwd=ROOT,
                                    capture_output=True, encoding="utf-8", timeout=120)
            calls += 1
            require(result.returncode == 0, f"CLI failed: {arguments}\n{result.stdout}\n{result.stderr}")
            value = json.loads(result.stdout)
            require(value.get("status") != "failed", f"Authoring failed: {value}")
            return value

        def write(commands, body):
            path = root / f"request-{calls}.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            return call(*commands, "--request", path)

        def action(identifier, operation, asset, parameters):
            require(operation in {"normalize/v1", "loop/v1", "scene/v1"}, "Only PCM operations belong in this smoke")
            result = write(["action", "execute"], {"schema": "matter-action/v1", "request_id": identifier,
                           "operation": operation, "inputs": [asset["asset_id"]], "parameters": parameters})
            require(result["status"] == "succeeded" and result["audio_model_calls"] == 0, "Expected zero-model PCM output")
            return result["outputs"][0]

        capabilities = call("capabilities")
        require(capabilities["product"] == PRODUCT and capabilities["core_version"] == "0.6.0", "Wrong product/core routing")
        require({"normalize/v1", "loop/v1", "scene/v1", "analyze/v1"}.issubset(
            {item["operation"] for item in capabilities["operations"]}), "M4 operations are missing")
        require(capabilities["cue_sets"]["availability"] == capabilities["library"]["availability"] == "available",
                "Cue packages or local search are unavailable")

        if PRODUCT == "score-matter":
            from matter_audio_core.media import PCM, encode_wav, sample_bytes
            source = root / "synthetic.wav"
            source.write_bytes(encode_wav(PCM(sample_bytes(array("h", [-2000, 0, 2000, 0] * 2000)), 8000, 1)))
            original = source.read_bytes()
            asset = call("assets", "import", source, "--request-id", "input")["outputs"][0]
        else:
            catalog = call("catalog", "list")
            require(catalog["decoder"]["availability"] == "available", "Recording decoder unavailable")
            registration = next(item for item in catalog["assets"] if item["source_asset_id"] == "starninjas.book-flip.08")
            source = Path(registration["path"])
            original = source.read_bytes()
            require(hashlib.sha256(original).hexdigest() == registration["digest"]["hex"], "Recording registration changed")
            decoded = call("catalog", "decode", registration["source_asset_id"], "--request-id", "input")
            require(decoded["audio_model_calls"] == 0, "Decoding must not call a model")
            asset = next(item for item in decoded["outputs"] if item["role"] == "audio")

        normalized = action("level", "normalize/v1", asset, {"target_rms_dbfs": -24, "max_boost_db": 24})
        analysis = call("analyze", normalized["asset_id"])["analysis"]
        require(analysis["rms_dbfs"] is not None, "Expected a non-silent measured fixture")
        end = min(4096, normalized["media"]["frame_count"])
        loop = action("loop", "loop/v1", normalized, {"start_frame": 0, "end_frame": end, "crossfade_frames": 64})
        length = loop["media"]["frame_count"]
        require(length == end - 64, "Unexpected overlap loop frame count")
        scene = action("scene", "scene/v1", loop, {"duration_frames": length * 2, "tracks": [{"name": "bed", "db": -6}],
            "events": [{"event_id": "repeat", "input_index": 0, "track": "bed", "source_start_frame": 0,
                        "source_end_frame": length, "offset_frame": 0, "repeat": 2}]})
        require(scene["media"]["frame_count"] == length * 2, "Scene duration changed")
        write(["session", "create"], {"schema": "matter-session-create/v1", "request_id": "session-create",
              "session_id": "check", "name": "Engineering fixture", "asset_id": loop["asset_id"]})
        package = write(["cue-set", "create"], {"schema": "matter-cue-set/v1", "set_id": "check-v1", "name": "Engineering fixtures",
            "cues": [{"key": "loop", "name": "Loop", "selected_variant": "main", "variants": [{"key": "main", "asset_id": loop["asset_id"],
                       "loop": {"begin_frame": 0, "end_frame": length}, "selection": {"session_id": "check", "revision": 1}}]},
                     {"key": "scene", "name": "Scene", "selected_variant": "main", "variants": [{"key": "main", "asset_id": scene["asset_id"]}]}]})
        delivery = write(["cue-set", "export"], {"schema": "matter-cue-export/v1", "request_id": "delivery", "set_id": "check-v1", "variants": "selected"})
        require(len(delivery["files"]) == 2, "Expected two exported WAV files")
        originals = {item["asset_id"]: (workspace / item["locator"]).read_bytes() for item in (loop, scene)}
        for entry in delivery["body"]["entries"]:
            require((Path(delivery["directory"]) / entry["filename"]).read_bytes() == originals[entry["asset"]["asset_id"]],
                    "Cue export changed the saved artifact bytes")
        require(call("cue-set", "export-show", "delivery") == delivery, "Export replay changed its receipt")
        require(call("cue-set", "show", "check-v1") == package, "Cue export changed the source package")
        write(["library", "create"], {"schema": "matter-library/v1", "library_id": "check", "name": "Engineering fixtures",
              "entries": [{"asset_id": item["asset_id"], "name": name, "tags": ["integration"]} for item, name in [(loop, "Loop"), (scene, "Scene")]]})
        matches = write(["library", "search"], {"schema": "matter-library-search/v1", "library_id": "check",
                        "tags": ["integration"], "similar_to": loop["asset_id"]})
        require(matches["total_matches"] == 2 and matches["items"][0]["asset_id"] == loop["asset_id"]
                and matches["items"][0]["distance"] == 0, "Measured search returned unexpected results")
        require(source.read_bytes() == original, "Authoring modified the original source")

    print(json.dumps({"status": "passed", "product": PRODUCT, "core_version": "0.6.0", "adapter_tests": outcome.testsRun,
                      "cli_calls": calls, "exported_wavs": 2, "exact_export_bytes": True,
                      "audio_model_calls": 0, "human_listening": "not_performed"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
