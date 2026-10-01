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
    for directory, pattern in [('tests', 'test_audio.py'), ('tests', 'test_sa3_edit.py'),
                               ('tests', 'test_candidate_registration.py'), ('tests', 'test_music_annotations.py'),
                               ('tests', 'test_music_arrangements.py'), ('tests', 'test_music_transitions.py'),
                               ('tests', 'test_music_arrangement_annotations.py')]:
        suite.addTests(loader.discover(str(ROOT / directory), pattern=pattern))
    outcome = unittest.TextTestRunner(verbosity=2).run(suite)
    require(outcome.wasSuccessful() and not outcome.skipped, "Shared audio tests must pass without skips")

    with tempfile.TemporaryDirectory(prefix="matter-product-check-") as temporary:
        root = Path(temporary)
        workspace = root / "workspace"
        calls = 0

        def call(*arguments, expected_error=None):
            nonlocal calls
            result = subprocess.run([sys.executable, "-m", *ENTRY, "--workspace", str(workspace),
                                     *map(str, arguments), "--json"], cwd=ROOT,
                                    capture_output=True, encoding="utf-8", timeout=120)
            calls += 1
            require(result.returncode == (2 if expected_error else 0),
                    f"CLI failed: {arguments}\n{result.stdout}\n{result.stderr}")
            value = json.loads(result.stdout)
            if expected_error:
                require(value.get("error", {}).get("code") == expected_error, f"Unexpected CLI failure: {value}")
                return value
            require(value.get("status") != "failed", f"Authoring failed: {value}")
            return value

        def write(commands, body, expected_error=None):
            path = root / f"request-{calls}.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            return call(*commands, "--request", path, expected_error=expected_error)

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
            registration_capability = capabilities["product_capabilities"]["candidate_registration"]
            require(registration_capability["file_parameters"] == ["--audio", "--generation-record", "--intent"],
                    "Candidate file parameters are missing")
            record = root / "generation.json"
            record.write_text(json.dumps({"kind": "score-matter-fast-generation", "status": "candidate",
                "output": {"path": "historical/not-opened.wav", "sha256": "sha256:" + hashlib.sha256(original).hexdigest(),
                           "media": {"container": "wav", "codec": "pcm_s16le", "sample_rate_hz": 8000,
                                     "channels": 1, "sample_width_bytes": 2, "frame_count": 8000}}}, indent=2), encoding="utf-8")
            intent = root / "intent.json"
            intent.write_text(json.dumps({"schema": "score-music-intent/v1", "source": "agent",
                                          "purpose": "Synthetic integration fixture", "preserve": ["Existing audio"]}), encoding="utf-8")
            registration_args = ("candidate", "register", "--audio", source, "--generation-record", record,
                                 "--intent", intent, "--request-id", "input")
            registered = call(*registration_args)
            require(registered["audio_model_calls"] == 0 and registered["status"] == "succeeded", "Candidate registration failed")
            require([item["role"] for item in registered["outputs"]] == ["audio", "generation_record", "music_intent"],
                    "Unexpected candidate publication")
            for item, expected in zip(registered["outputs"], (original, record.read_bytes(), intent.read_bytes())):
                require((workspace / item["locator"]).read_bytes() == expected, "Candidate publication changed original bytes")
            require(call(*registration_args) == registered, "Candidate retry changed its receipt")
            require(call("action", "show", "input") == registered, "Candidate query changed its receipt")
            require(not (workspace / "sessions.sqlite3").exists(), "Registration created a session")
            asset = registered["outputs"][0]
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

        if PRODUCT == "score-matter":
            from matter_audio_core.media import decode_wav
            require(capabilities["product_capabilities"]["music"]["rounding"] == "rational-half-up/v1",
                    "Musical coordinates must advertise their rounding profile")
            annotation_request = {"schema": "score-music-annotate/v1", "request_id": "music-annotation",
                "asset_id": asset["asset_id"], "source": "agent",
                "timing": {"mode": "fixed", "bpm": "120", "bpm_unit": {"numerator": 3, "denominator": 8},
                           "meter": {"beats": 6, "unit": 8}, "origin_frame": 0},
                "regions": [{"id": "half", "start": {"bar": 1, "beat": "1"}, "end": {"bar": 1, "beat": "4"}},
                            {"id": "bar", "start": {"bar": 1, "beat": "1"}, "end": {"bar": 2, "beat": "1"}}]}
            annotation = write(["music", "annotate"], annotation_request)
            annotation_id = annotation["outputs"][0]["asset_id"]
            require(write(["music", "annotate"], annotation_request) == annotation, "Music annotation replay changed")
            saved_annotation = call("music", "show", annotation_id)["document"]
            require(saved_annotation["audio"]["asset_id"] == asset["asset_id"]
                    and saved_annotation["audio"]["digest"] == asset["digest"], "Music annotation lost exact audio binding")
            trim_request = {"schema": "score-music-plan/v1", "request_id": "music-trim-plan",
                "annotation_id": annotation_id, "region_ids": ["half"], "target": {"kind": "trim"}}
            trim_plan = write(["music", "plan"], trim_request)
            require(len(trim_plan["outputs"]) == 1 and trim_plan["outputs"][0]["role"] == "music_plan",
                    "Planning must publish metadata only")
            call("action", "show", trim_plan["document"]["core_request"]["request_id"], expected_error="request_not_found")
            trim_result = call("music", "execute", trim_plan["outputs"][0]["asset_id"])
            require(trim_result["audio_model_calls"] == 0 and trim_result["outputs"][0]["media"]["frame_count"] == 4000,
                    "6/8 dotted-quarter trim has the wrong duration")
            require(decode_wav((workspace / trim_result["outputs"][0]["locator"]).read_bytes()).payload
                    == decode_wav(original).payload[:8000], "Music trim changed selected PCM")
            require(not (workspace / "sessions.sqlite3").exists(), "Musical annotation or execution created a session")
            loop_request = {**trim_request, "request_id": "music-loop-plan", "region_ids": ["bar"],
                            "target": {"kind": "loop", "crossfade_frames": 64}}
            music_loop_plan = write(["music", "plan"], loop_request)
            music_loop_result = call("music", "execute", music_loop_plan["outputs"][0]["asset_id"])
            music_loop = music_loop_result["outputs"][0]
            period = music_loop_plan["document"]["loop"]
            require(period["source_window_frames"] == 8000 and period["removed_frames"] == 64
                    and period["period_frames"] == music_loop["media"]["frame_count"] == 7936
                    and period["period_seconds"] == "124/125", "Overlap must shorten the advertised musical period")
            require(call("music", "execute", music_loop_plan["outputs"][0]["asset_id"]) == music_loop_result,
                    "Music execution replay changed its receipt")
            require(saved_annotation == call("music", "show", annotation_id)["document"], "Editing changed source annotations")
            write(["session", "create"], {"schema": "matter-session-create/v1", "request_id": "music-session-create",
                  "session_id": "music-check", "name": "Musical engineering fixture", "asset_id": asset["asset_id"]})
            lock_plan = write(["music", "plan"], {**trim_request, "request_id": "music-lock-plan",
                "target": {"kind": "constraints", "session_id": "music-check", "expected_revision": 1}})
            call("music", "execute", lock_plan["outputs"][0]["asset_id"])
            music_context = call("context", "show", "music-check")
            require(music_context["current"]["selected_asset"]["asset_id"] == asset["asset_id"]
                    and music_context["feedback"] == [], "Music planning selected an edit or invented listening feedback")

            replacement_source = root / "replacement.wav"
            replacement_bytes = encode_wav(PCM(sample_bytes(array("h", [1500 + i % 500 for i in range(10000)])), 8000, 1))
            replacement_source.write_bytes(replacement_bytes)
            replacement_audio = call("candidate", "register", "--audio", replacement_source,
                                     "--request-id", "replacement-input")["outputs"][0]
            replacement_annotation = write(["music", "annotate"], {
                "schema": "score-music-annotate/v1", "request_id": "replacement-annotation",
                "asset_id": replacement_audio["asset_id"], "source": "agent", "timing": {"mode": "free"},
                "regions": [{"id": "alternate", "start": {"frame": 500}, "end": {"frame": 4500}}]})
            splice_plan = write(["music", "plan"], {**trim_request, "request_id": "music-splice-plan",
                "target": {"kind": "splice", "transition_frames": 0,
                           "replacement": {"annotation_id": replacement_annotation["outputs"][0]["asset_id"],
                                           "region_id": "alternate"}}})
            splice_id = splice_plan["outputs"][0]["asset_id"]
            splice_document = call("music", "show", splice_id)["document"]
            require(splice_document["core_request"]["inputs"] == [asset["asset_id"], replacement_audio["asset_id"]]
                    and splice_document["replacement"]["audio"]["digest"] == replacement_audio["digest"],
                    "Splice plan lost one of its exact source bindings")
            splice_result = call("music", "execute", splice_id)
            splice_audio = splice_result["outputs"][0]
            expected_pcm = decode_wav(replacement_bytes).payload[1000:9000] + decode_wav(original).payload[8000:]
            require(decode_wav((workspace / splice_audio["locator"]).read_bytes()).payload == expected_pcm
                    and splice_audio["media"]["frame_count"] == 8000, "Named splice changed PCM outside its window or adapted duration")
            require(splice_result["audio_model_calls"] == 0
                    and splice_result["findings"][0]["observed_changes"]["outside_changed_sample_count"] == 0,
                    "Named splice must be a bounded zero-model operation")
            require(call("music", "execute", splice_id) == splice_result, "Splice replay changed its receipt")
            call("music", "show", splice_audio["asset_id"], expected_error="invalid_music_plan")
            require(call("context", "show", "music-check") == music_context, "Splice selected its output or altered session metadata")
            require(replacement_source.read_bytes() == replacement_bytes, "Splice changed the replacement source")

            arrange_request = {"schema": "score-music-arrange/v1", "request_id": "music-arrange-plan", "segments": [
                {"id": "a-start", "annotation_id": annotation_id, "region_id": "half", "repeat": 1},
                {"id": "b-repeat", "annotation_id": replacement_annotation["outputs"][0]["asset_id"], "region_id": "alternate", "repeat": 2},
                {"id": "a-end", "annotation_id": annotation_id, "region_id": "half", "repeat": 1}]}
            arranged = write(["music", "arrange"], arrange_request)
            arrangement_id = arranged["outputs"][0]["asset_id"]
            require([item["role"] for item in arranged["outputs"]] == ["music_arrangement"], "Arrangement planning must only save a plan")
            arranged_document = call("music", "show", arrangement_id)["document"]
            require(arranged_document["duration_frames"] == 16000
                    and [(item["start_frame"], item["end_frame"]) for item in arranged_document["timeline"]]
                    == [(0, 4000), (4000, 8000), (8000, 12000), (12000, 16000)], "Arrangement sequence or repeat offsets changed")
            arranged_result = call("music", "execute", arrangement_id)
            arranged_audio = arranged_result["outputs"][0]
            a_pcm, b_pcm = decode_wav(original).payload[:8000], decode_wav(replacement_bytes).payload[1000:9000]
            require(decode_wav((workspace / arranged_audio["locator"]).read_bytes()).payload == a_pcm + b_pcm * 2 + a_pcm
                    and arranged_audio["media"]["frame_count"] == 16000, "Arrangement must copy A, B twice, then A exactly")
            require(arranged_result["audio_model_calls"] == 0, "Arrangement called a model")
            require(write(["music", "arrange"], arrange_request) == arranged, "Arrangement plan retry changed its receipt")
            require(call("music", "execute", arrangement_id) == arranged_result, "Arrangement execution retry changed its receipt")
            call("music", "show", arranged_audio["asset_id"], expected_error="invalid_music_plan")
            require(call("context", "show", "music-check") == music_context, "Arrangement changed source selection, locks or feedback")

            transition_request = {"schema": "score-music-arrange/v2", "request_id": "music-transition-plan", "segments": [
                {"id": "a-repeat", "annotation_id": annotation_id, "region_id": "half", "repeat": 2},
                {"id": "b", "annotation_id": replacement_annotation["outputs"][0]["asset_id"], "region_id": "alternate", "repeat": 1}],
                "transitions": [{"after_segment_id": "a-repeat", "after_repeat_index": 1, "crossfade_frames": 3}]}
            transition_plan = write(["music", "arrange"], transition_request)
            transition_id = transition_plan["outputs"][0]["asset_id"]
            transition_document = call("music", "show", transition_id)["document"]
            require([(item["start_frame"], item["end_frame"], item["body_start_frame"], item["body_end_frame"])
                     for item in transition_document["timeline"]]
                    == [(0, 4000, 0, 4000), (4000, 8000, 4000, 7997), (7997, 11997, 8000, 11997)],
                    "Only the second A/B boundary may overlap")
            derived_request = {"schema": "score-music-annotate-arrangement/v1", "request_id": "finished-music-annotation",
                "plan_id": transition_id, "source": "agent", "regions": [
                    {"id": "keep", "segment_id": "a-repeat", "repeat_index": 0, "range": "full"},
                    {"id": "edit", "segment_id": "a-repeat", "repeat_index": 1, "range": "body"},
                    {"id": "replacement", "segment_id": "b", "repeat_index": 0, "range": "body"}]}
            write(["music", "annotate-arrangement"], derived_request, expected_error="music_arrangement_not_completed")
            transition_result = call("music", "execute", transition_id)
            transition_audio = transition_result["outputs"][0]
            # The three-frame overlap has weights (1,0), (1/2,1/2), (0,1).
            # This oracle uses fixture samples, independently of the scene planner.
            a_samples = list(decode_wav(original).samples())[:4000]
            b_samples = list(decode_wav(replacement_bytes).samples())[500:4500]
            mixed_middle = a_samples[-2] + b_samples[1]
            mixed_middle = (mixed_middle + 1) // 2 if mixed_middle >= 0 else -((-mixed_middle + 1) // 2)
            transition_samples = a_samples + a_samples[:-3] + [a_samples[-3], mixed_middle, b_samples[2]] + b_samples[3:]
            transition_raw = (workspace / transition_audio["locator"]).read_bytes()
            transition_pcm = decode_wav(transition_raw).payload
            require(list(decode_wav(transition_raw).samples()) == transition_samples
                    and transition_audio["media"]["frame_count"] == 11997, "Transition PCM or shortened length changed")
            require(transition_result["audio_model_calls"] == 0, "Transition launched a model")
            call("music", "show", transition_audio["asset_id"], expected_error="invalid_music_plan")
            derived = write(["music", "annotate-arrangement"], derived_request)
            derived_id = derived["outputs"][0]["asset_id"]
            derived_document = call("music", "show", derived_id)["document"]
            require(derived_document["timing"] == {"mode": "unknown"}
                    and derived_document["audio"]["asset_id"] == transition_audio["asset_id"]
                    and [(r["start_frame"], r["end_frame"]) for r in derived_document["resolved_regions"]]
                    == [(0, 4000), (4000, 7997), (8000, 11997)], "Finished annotation inherited a grid or mapped the wrong body")
            require(write(["music", "annotate-arrangement"], derived_request) == derived, "Finished annotation replay changed")
            require(call("context", "show", "music-check") == music_context, "Finishing altered the source session or feedback")
            write(["session", "create"], {"schema": "matter-session-create/v1", "request_id": "finished-session-create",
                "session_id": "finished", "name": "Explicit finished arrangement", "asset_id": transition_audio["asset_id"]})
            finished_lock_plan = write(["music", "plan"], {"schema": "score-music-plan/v1", "request_id": "finished-lock-plan",
                "annotation_id": derived_id, "region_ids": ["keep"],
                "target": {"kind": "constraints", "session_id": "finished", "expected_revision": 1}})
            call("music", "execute", finished_lock_plan["outputs"][0]["asset_id"])
            locked_context = call("context", "show", "finished")
            body_plan = write(["music", "plan"], {"schema": "score-music-plan/v1", "request_id": "finished-body-plan",
                "annotation_id": derived_id, "region_ids": ["edit"], "target": {"kind": "splice", "transition_frames": 0,
                    "replacement": {"annotation_id": derived_id, "region_id": "replacement"},
                    "protection": {"session_id": "finished", "revision": 2}}})
            body_result = call("music", "execute", body_plan["outputs"][0]["asset_id"])
            body_audio = body_result["outputs"][0]
            body_raw = (workspace / body_audio["locator"]).read_bytes()
            body_pcm = decode_wav(body_raw).payload
            require(body_pcm == transition_pcm[:8000] + transition_pcm[16000:23994] + transition_pcm[15994:]
                    and body_pcm[:8000] == transition_pcm[:8000] and body_pcm[15994:] == transition_pcm[15994:],
                    "Body editing changed locked PCM or the adjacent transition")
            require(body_result["findings"][0]["protection"]["status"] == "verified"
                    and body_result["audio_model_calls"] == 0, "Body editing lost its PCM lock or launched a model")
            require(call("context", "show", "finished") == locked_context, "Body editing selected its own output")
            call("music", "show", body_audio["asset_id"], expected_error="invalid_music_plan")
            write(["session", "select"], {"schema": "matter-session-select/v1", "request_id": "finished-select-body",
                "session_id": "finished", "expected_revision": 2, "asset_id": body_audio["asset_id"]})
            finished_context = call("context", "show", "finished")
            require(finished_context["current"]["selected_asset"]["asset_id"] == body_audio["asset_id"]
                    and finished_context["feedback"] == [], "Explicit selection or feedback is incorrect")
            require(finished_context["constraints"]["mapped_regions"] == locked_context["constraints"]["mapped_regions"]
                    and [(item["start_frame"], item["end_frame"]) for item in finished_context["constraints"]["mapped_regions"]]
                    == [(0, 4000)], "Selected edit changed the exact protected region or its PCM digest")
            write(["cue-set", "create"], {"schema": "matter-cue-set/v1", "set_id": "finished-cue", "name": "Finished music",
                "cues": [{"key": "finished", "name": "Finished", "selected_variant": "main", "variants": [
                    {"key": "main", "asset_id": body_audio["asset_id"], "selection": {"session_id": "finished", "revision": 3}}]}]})
            finished_delivery = write(["cue-set", "export"], {"schema": "matter-cue-export/v1", "request_id": "finished-delivery",
                "set_id": "finished-cue", "variants": "selected"})
            require(len(finished_delivery["body"]["entries"]) == 1, "Finished delivery must contain the selected version")
            exported = finished_delivery["body"]["entries"][0]
            require((Path(finished_delivery["directory"]) / exported["filename"]).read_bytes() == body_raw,
                    "Finished export changed WAV bytes")
            require(call("context", "show", "music-check") == music_context
                    and source.read_bytes() == original and replacement_source.read_bytes() == replacement_bytes,
                    "Finishing changed source sessions, feedback or recordings")

        write(["session", "create"], {"schema": "matter-session-create/v1", "request_id": "session-create",
              "session_id": "check", "name": "Engineering fixture"})
        selection = {"schema": "matter-session-select/v1", "request_id": "select-input", "session_id": "check",
                     "expected_revision": 1, "asset_id": asset["asset_id"]}
        selected = write(["session", "select"], selection)
        require(write(["session", "select"], selection) == selected, "Selection retry changed its receipt")

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
        write(["session", "select"], {**selection, "request_id": "select-loop", "expected_revision": 2,
                                      "asset_id": loop["asset_id"]})
        write(["session", "select"], {**selection, "request_id": "stale-selection", "asset_id": scene["asset_id"]},
              expected_error="revision_conflict")
        context = call("context", "show", "check")
        require(context["current"]["selected_asset"]["asset_id"] == loop["asset_id"] and context["feedback"] == [],
                "Stale selection changed current audio or intent became feedback")
        package = write(["cue-set", "create"], {"schema": "matter-cue-set/v1", "set_id": "check-v1", "name": "Engineering fixtures",
            "cues": [{"key": "loop", "name": "Loop", "selected_variant": "main", "variants": [{"key": "main", "asset_id": loop["asset_id"],
                       "loop": {"begin_frame": 0, "end_frame": length}, "selection": {"session_id": "check", "revision": 3}}]},
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
                      "cli_calls": calls, "exported_wavs": 3 if PRODUCT == "score-matter" else 2, "exact_export_bytes": True,
                      "music_coordinates": "explicit_grid_and_immutable_plan", "loop_period_accounts_for_overlap": True,
                      "music_splice": "equal_frames_exact_outside_pcm_no_automatic_selection",
                      "music_arrangement": "a_b_twice_a_exact_pcm_no_automatic_selection",
                      "music_finishing": "explicit_seam_body_annotation_locked_splice_select_exact_export",
                      "audio_model_calls": 0, "human_listening": "not_performed"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
