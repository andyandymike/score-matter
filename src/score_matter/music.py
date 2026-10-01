"""Immutable musical annotations and explicit plans over existing Core assets."""
from __future__ import annotations

import argparse
from fractions import Fraction
from pathlib import Path

from matter_audio_core.actions import ActionService
from matter_audio_core.artifacts import ArtifactStore, stable_read
from matter_audio_core.contracts import (
    ASSET_PATTERN, MAX_JSON_BYTES, PROTECTION_REF, REQUEST_PATTERN,
    canonical, fingerprint, object_schema, parse_json, validate,
)
from matter_audio_core.errors import AudioError
from matter_audio_core.fades import FRAME_COUNT
from matter_audio_core.media import decode_wav
from matter_audio_core.session_contracts import CONSTRAINTS_SCHEMA, REVISION
from matter_audio_core.sessions import SessionService


ROUNDING = "rational-half-up/v1"
IDENTIFIER = {"type": "string", "pattern": REQUEST_PATTERN}
ASSET_ID = {"type": "string", "pattern": ASSET_PATTERN}
DECIMAL = {"type": "string", "pattern": r"^(0|[1-9][0-9]{0,8})(\.[0-9]{1,9})?$"}
UNIT = {"type": "integer", "enum": [1, 2, 4, 8, 16, 32]}
TIMING_SCHEMA = {"oneOf": [
    object_schema({"mode": {"const": "fixed"}, "bpm": DECIMAL,
                   "bpm_unit": object_schema({"numerator": {"type": "integer", "minimum": 1, "maximum": 32},
                                               "denominator": UNIT}),
                   "meter": object_schema({"beats": {"type": "integer", "minimum": 1, "maximum": 32}, "unit": UNIT}),
                   "origin_frame": FRAME_COUNT}),
    object_schema({"mode": {"enum": ["free", "unknown"]}}),
]}
POSITION_SCHEMA = {"oneOf": [object_schema({"frame": FRAME_COUNT}), object_schema({"seconds": DECIMAL}),
    object_schema({"bar": {"type": "integer", "minimum": 1, "maximum": 1000000}, "beat": DECIMAL})]}
REGION_SCHEMA = object_schema({"id": IDENTIFIER, "start": POSITION_SCHEMA, "end": POSITION_SCHEMA})
ANNOTATE_SCHEMA = object_schema({
    "schema": {"const": "score-music-annotate/v1"}, "request_id": IDENTIFIER, "asset_id": ASSET_ID,
    "source": {"enum": ["user", "agent", "project", "unknown"]}, "timing": TIMING_SCHEMA,
    "regions": {"type": "array", "minItems": 1, "maxItems": 128, "items": REGION_SCHEMA},
})
TARGET_SCHEMA = {"oneOf": [
    object_schema({"kind": {"const": "trim"}, "protection": PROTECTION_REF}, ["kind"]),
    object_schema({"kind": {"const": "loop"}, "crossfade_frames": FRAME_COUNT,
                   "curve": {"enum": ["linear", "equal_power"]}, "clip": {"enum": ["reject", "saturate"]},
                   "protection": PROTECTION_REF}, ["kind", "crossfade_frames"]),
    object_schema({"kind": {"const": "splice"},
                   "replacement": object_schema({"annotation_id": ASSET_ID, "region_id": IDENTIFIER}),
                   "transition_frames": FRAME_COUNT, "protection": PROTECTION_REF},
                  ["kind", "replacement", "transition_frames"]),
    object_schema({"kind": {"const": "constraints"}, "session_id": IDENTIFIER, "expected_revision": REVISION}),
]}
PLAN_SCHEMA = object_schema({
    "schema": {"const": "score-music-plan/v1"}, "request_id": IDENTIFIER, "annotation_id": ASSET_ID,
    "region_ids": {"type": "array", "minItems": 1, "maxItems": 16, "uniqueItems": True, "items": IDENTIFIER},
    "target": TARGET_SCHEMA,
})
LIMITATIONS = [
    "Musical timing and section names are supplied annotations, not measured beat detection or listening feedback.",
    "Only fixed tempo is supported; free and unknown timing accept frames or seconds only.",
    "Plans do not edit audio or change sessions until explicitly executed. Audio results are not automatically selected.",
    "Constraints plans only add locks; removing locks requires the explicit Core constraints workflow.",
    "Annotations are bound to one exact asset and are not inherited by edited outputs.",
    "Loop overlap shortens the period; successful execution does not establish musical or listening acceptance.",
    "Splice requires equal resolved region lengths and matching sample rate/channels; it never truncates, resamples or time-stretches a replacement.",
    "Protection references retain Core constraint-set semantics; they do not require the latest selection revision.",
]


def capabilities():
    from .music_arrangement import ARRANGE_SCHEMA, LIMITS, LIMITATIONS as ARRANGEMENT_LIMITATIONS
    return {"music": {"availability": "available", "commands": ["music annotate", "music show", "music plan", "music arrange", "music execute"],
        "file_parameters": ["--request"], "request_schemas": {"annotate": ANNOTATE_SCHEMA, "plan": PLAN_SCHEMA, "arrange": ARRANGE_SCHEMA},
        "rounding": ROUNDING, "decimal_input": "Exact nonnegative decimal strings, at most nine fractional digits",
        "bpm_unit": "Fraction of a whole note; 1/4 is a quarter, 3/8 is a dotted quarter",
        "coordinates": "One-based bars and beats; beat unit is the meter denominator; half-open regions",
        "metadata_roles": ["music_annotation", "music_plan", "music_arrangement"], "constraints_mode": "add_only_union",
        "execution_identity": "music- plus SHA-256 of plan request and exact annotation/audio references",
        "splice": {"length_rule": "equal_resolved_frame_count", "format_rule": "same_sample_rate_and_channels",
                   "protection_target": "base", "transition_rule": "inside_target_window_without_overlap"},
        "arrangement": {"mode": "sequential_integer_repeats", "limits": LIMITS,
                        "repeat_index": "zero_based", "input_identity": "asset_id_first_appearance",
                        "limitations": ARRANGEMENT_LIMITATIONS},
        "limitations": LIMITATIONS}}


def _audio(store, asset_id):
    record, data = store.asset(asset_id)
    if record["media"].get("codec") != "pcm_s16le":
        raise AudioError("unsupported_music_asset", "Musical annotations require an existing PCM16 WAV asset")
    decode_wav(data)
    return {key: record[key] for key in ("asset_id", "digest", "media")}


def _ref(record):
    return {key: record[key] for key in ("asset_id", "digest")}


def _timing(timing, media):
    validate(timing, TIMING_SCHEMA)
    if timing["mode"] == "fixed":
        if not 0 < Fraction(timing["bpm"]) <= 1000:
            raise AudioError("invalid_music_timing", "BPM must be greater than zero and at most 1000")
        if timing["origin_frame"] > media["frame_count"]:
            raise AudioError("invalid_music_timing", "First-beat origin must be inside the audio")


def resolve_position(point, timing, media):
    """Calculate from the absolute origin, then round once (nonnegative half up)."""
    validate(point, POSITION_SCHEMA)
    _timing(timing, media)
    rate, count = media["sample_rate_hz"], media["frame_count"]
    if "frame" in point:
        exact = Fraction(point["frame"])
    elif "seconds" in point:
        exact = Fraction(point["seconds"]) * rate
    else:
        if timing["mode"] != "fixed":
            raise AudioError("music_grid_required", "Bar/beat positions require an explicit fixed-tempo grid")
        beat = Fraction(point["beat"])
        meter = timing["meter"]
        if not 1 <= beat < meter["beats"] + 1:
            raise AudioError("invalid_music_position", "Beat must be in this bar; use the next bar for its first beat")
        whole_notes = ((point["bar"] - 1) * meter["beats"] + beat - 1) / meter["unit"]
        bpm_unit = Fraction(timing["bpm_unit"]["numerator"], timing["bpm_unit"]["denominator"])
        exact = timing["origin_frame"] + whole_notes / bpm_unit * 60 * rate / Fraction(timing["bpm"])
    if not 0 <= exact <= count:
        raise AudioError("music_position_out_of_range", "Exact musical position lies outside the bound audio")
    rounded = (2 * exact.numerator + exact.denominator) // (2 * exact.denominator)
    error = rounded - exact
    return {"frame": rounded, "exact_frame": str(exact), "error_frames": str(error), "error_seconds": str(error / rate)}


def _annotation_document(store, request):
    validate(request, ANNOTATE_SCHEMA)
    audio = _audio(store, request["asset_id"])
    _timing(request["timing"], audio["media"])
    resolved, seen = [], set()
    for region in request["regions"]:
        if region["id"] in seen:
            raise AudioError("duplicate_music_region", "Region IDs must be unique")
        seen.add(region["id"])
        start = resolve_position(region["start"], request["timing"], audio["media"])
        end = resolve_position(region["end"], request["timing"], audio["media"])
        if Fraction(start["exact_frame"]) >= Fraction(end["exact_frame"]) or start["frame"] >= end["frame"]:
            raise AudioError("invalid_music_region", "Regions must remain nonempty after frame quantization")
        resolved.append({"id": region["id"], "start": start, "end": end,
                         "start_frame": start["frame"], "end_frame": end["frame"]})
    return {"schema": "score-music-annotation/v1", "request": request, "audio": audio,
            "resolved_regions": resolved, "rounding": ROUNDING}


def _publish(store, request_id, binding, document, role, parents):
    data = canonical(document)
    if len(data) > MAX_JSON_BYTES:
        raise AudioError("json_too_large", "Musical document exceeds 1 MiB")

    def produce(publication):
        output = publication.add(data, {"kind": role, "content_type": "application/json"}, role=role, parents=parents)
        return {"annotation" if role == "music_annotation" else "plan": output, "document": document,
                "limitations": LIMITATIONS}

    return store.transact(request_id, binding, produce)


def annotate(store: ArtifactStore, request):
    document = _annotation_document(store, request)
    return _publish(store, request["request_id"], {"operation": "score.music.annotate/v1", "document": document},
                    document, "music_annotation", [{"role": "annotates", **_ref(document["audio"])}])


def _load_annotation(store, asset_id):
    record, raw = store.asset(asset_id)
    if record["role"] != "music_annotation":
        raise AudioError("invalid_music_annotation", "Expected a saved music annotation asset")
    document = parse_json(raw)
    if not isinstance(document, dict) or document.get("schema") != "score-music-annotation/v1":
        raise AudioError("invalid_music_annotation", "Expected a saved music annotation asset")
    if document != _annotation_document(store, document["request"]):
        raise AudioError("music_binding_mismatch", "Annotation does not match its source asset or resolved coordinates")
    return record, document


def _plan_base(store, request):
    validate(request, PLAN_SCHEMA)
    record, annotation = _load_annotation(store, request["annotation_id"])
    lookup = {region["id"]: region for region in annotation["resolved_regions"]}
    if any(name not in lookup for name in request["region_ids"]):
        raise AudioError("music_region_not_found", "Requested region is absent from this exact annotation")
    if request["target"]["kind"] != "constraints" and len(request["region_ids"]) != 1:
        raise AudioError("invalid_music_plan", "Trim, loop and splice plans accept exactly one base region")
    binding = {"operation": "score.music.plan/v1", "request": request,
               "annotation": _ref(record), "audio": annotation["audio"]}
    regions = [lookup[name] for name in request["region_ids"]]
    if request["target"]["kind"] == "splice":
        replacement = request["target"]["replacement"]
        other_record, other = _load_annotation(store, replacement["annotation_id"])
        other_region = next((region for region in other["resolved_regions"] if region["id"] == replacement["region_id"]), None)
        if other_region is None:
            raise AudioError("music_region_not_found", "Replacement region is absent from this exact annotation")
        if any(annotation["audio"]["media"][key] != other["audio"]["media"][key] for key in ("sample_rate_hz", "channels")):
            raise AudioError("music_splice_format_mismatch", "Base and replacement must share sample rate and channels")
        base_frames = regions[0]["end_frame"] - regions[0]["start_frame"]
        replacement_frames = other_region["end_frame"] - other_region["start_frame"]
        if base_frames != replacement_frames:
            raise AudioError("music_splice_length_mismatch", "Complete named regions must resolve to exactly equal frame lengths",
                             details={"base_frames": base_frames, "replacement_frames": replacement_frames})
        # Keep legacy bindings byte-for-byte equivalent: only splice adds this snapshot.
        binding["replacement"] = {"annotation": _ref(other_record), "audio": other["audio"], "region": other_region}
    return binding, regions


def _union(regions):
    merged = []
    for region in sorted(regions, key=lambda region: (region["start_frame"], region["end_frame"])):
        if merged and region["start_frame"] <= merged[-1]["end_frame"]:
            merged[-1]["end_frame"] = max(merged[-1]["end_frame"], region["end_frame"])
        else:
            merged.append({"start_frame": region["start_frame"], "end_frame": region["end_frame"]})
    if len(merged) > 16:
        raise AudioError("music_constraint_limit", "Combined existing and new protection exceeds 16 regions")
    return merged


def _core_request(binding, regions, existing=()):
    target = binding["request"]["target"]
    request_id = "music-" + fingerprint(binding)["hex"]
    windows = [{key: region[key] for key in ("start_frame", "end_frame")} for region in regions]
    if target["kind"] == "constraints":
        request = {"schema": "matter-constraints-set/v1", "request_id": request_id,
                   "session_id": target["session_id"], "expected_revision": target["expected_revision"],
                   "regions": _union([*existing, *windows])}
        validate(request, CONSTRAINTS_SCHEMA)
        return request
    request = {"schema": "matter-action/v1", "request_id": request_id, "operation": target["kind"] + "/v1",
               "inputs": [binding["audio"]["asset_id"]], "parameters": windows[0]}
    if target["kind"] == "loop":
        request["parameters"].update({key: target[key] for key in ("crossfade_frames", "curve", "clip") if key in target})
    elif target["kind"] == "splice":
        request["inputs"].append(binding["replacement"]["audio"]["asset_id"])
        request["parameters"].update({"replacement_start_frame": binding["replacement"]["region"]["start_frame"],
                                      "transition_frames": target["transition_frames"]})
    if "protection" in target:
        request["protection"] = target["protection"]
    return request


def _loop_period(resolution, audio):
    parameters = resolution["effective_parameters"]
    return {"source_window_frames": parameters["end_frame"] - parameters["start_frame"],
            "period_frames": parameters["output_frames"],
            "period_seconds": str(Fraction(parameters["output_frames"], audio["media"]["sample_rate_hz"])),
            "removed_frames": parameters["crossfade_frames"], "source_start_frame": parameters["output_source_start_frame"]}


def _existing_regions(store, target, audio):
    service = SessionService(store)
    # Core 0.6 has no public single-revision getter. Reuse its historical query
    # inside its checked read transaction; do not infer history from today's head.
    with service.database.transaction() as connection:
        row = service._revision(connection, target["session_id"], target["expected_revision"])
        selected = parse_json(row["asset_json"].encode("utf-8"))
    if selected != audio:
        raise AudioError("music_session_asset_mismatch", "Historical session selection differs from the plan's exact annotated audio")
    mapped = service.constraints(target["session_id"], revision=target["expected_revision"])["mapped_regions"]
    return [{key: region[key] for key in ("start_frame", "end_frame")} for region in mapped]


def plan(store: ArtifactStore, request):
    binding, regions = _plan_base(store, request)
    # Replay the frozen plan before consulting session state that may have moved.
    try:
        previous = store.show_request(request["request_id"])
    except AudioError as exc:
        if exc.code != "request_not_found":
            raise
    else:
        if previous["binding"] != binding:
            raise AudioError("request_conflict", "Plan request ID already binds different musical inputs")
        return previous
    document = {"schema": "score-music-plan-document/v1", "request": request,
                "annotation": binding["annotation"], "audio": binding["audio"],
                "resolved_regions": regions, "rounding": ROUNDING}
    target = request["target"]
    if target["kind"] == "splice":
        document["replacement"] = binding["replacement"]
    if target["kind"] == "constraints":
        service = SessionService(store)
        context = service.show(target["session_id"])
        if context["current"]["revision"] != target["expected_revision"]:
            raise AudioError("revision_conflict", "Read the current session before planning additional locks")
        if context["current"]["selected_asset"] != binding["audio"]:
            raise AudioError("music_session_asset_mismatch", "Additional locks require this exact annotated audio to be selected")
        existing = _existing_regions(store, target, binding["audio"])
        document["existing_regions"] = existing
        document["core_request"] = _core_request(binding, regions, existing)
    else:
        document["core_request"] = _core_request(binding, regions)
        document["core_resolution"] = ActionService(store).resolve(document["core_request"])
        document["expected_resolution_digest"] = document["core_resolution"]["digest"]["hex"]
        if target["kind"] == "loop":
            document["loop"] = _loop_period(document["core_resolution"], binding["audio"])
    parents = [{"role": "annotation", **binding["annotation"]}, {"role": "source", **_ref(binding["audio"])}]
    if target["kind"] == "splice":
        parents.extend([{"role": "replacement_annotation", **binding["replacement"]["annotation"]},
                        {"role": "replacement_source", **_ref(binding["replacement"]["audio"])}])
    return _publish(store, request["request_id"], binding, document, "music_plan", parents)


def _load_plan(store, asset_id):
    record, raw = store.asset(asset_id)
    if record["role"] != "music_plan":
        raise AudioError("invalid_music_plan", "Expected a saved music plan asset")
    document = parse_json(raw)
    if not isinstance(document, dict) or document.get("schema") != "score-music-plan-document/v1":
        raise AudioError("invalid_music_plan", "Expected a saved music plan asset")
    binding, regions = _plan_base(store, document["request"])
    if (document["annotation"] != binding["annotation"] or document["audio"] != binding["audio"]
            or document.get("replacement") != binding.get("replacement")
            or document["resolved_regions"] != regions or document["rounding"] != ROUNDING
            or document["core_request"] != _core_request(binding, regions, document.get("existing_regions", []))):
        raise AudioError("music_binding_mismatch", "Plan does not match its annotation, audio or frozen Core request")
    if document["request"]["target"]["kind"] == "constraints":
        # Recheck the immutable historical revision, never the current head.
        if document["existing_regions"] != _existing_regions(store, document["request"]["target"], binding["audio"]):
            raise AudioError("music_binding_mismatch", "Plan's existing locks differ from its bound historical revision")
    else:
        resolution = document["core_resolution"]
        body = {key: value for key, value in resolution.items() if key != "digest"}
        if (resolution["request"] != document["core_request"] or fingerprint(body) != resolution["digest"]
                or document["expected_resolution_digest"] != resolution["digest"]["hex"]):
            raise AudioError("music_binding_mismatch", "Stored Core resolution does not match the plan")
        if document["request"]["target"]["kind"] == "loop" and document["loop"] != _loop_period(resolution, binding["audio"]):
            raise AudioError("music_binding_mismatch", "Stored loop period differs from the resolved operation")
    return record, document


def show(store: ArtifactStore, asset_id):
    record, _ = store.asset(asset_id)
    if record["role"] == "music_annotation":
        record, document = _load_annotation(store, asset_id)
    elif record["role"] == "music_arrangement":
        from .music_arrangement import load
        record, document = load(store, asset_id)
    else:
        record, document = _load_plan(store, asset_id)
    return {"schema": "score-music-document/v1", "asset": record, "document": document, "audio_model_calls": 0}


def execute(store: ArtifactStore, plan_asset_id):
    if store.asset(plan_asset_id)[0]["role"] == "music_arrangement":
        from .music_arrangement import execute as execute_arrangement
        return execute_arrangement(store, plan_asset_id)
    record, document = _load_plan(store, plan_asset_id)
    request = document["core_request"]
    if document["request"]["target"]["kind"] == "constraints":
        # Core checks committed request identity before checking a new mutation's revision.
        result = SessionService(store).mutate("constraints", request)
    else:
        try:
            result = store.show_request(request["request_id"])
        except AudioError as exc:
            if exc.code != "request_not_found":
                raise
            result = ActionService(store).execute(request, expected_resolution_digest=document["expected_resolution_digest"])
        else:
            if result["binding"] != {"resolution": document["core_resolution"]}:
                raise AudioError("request_conflict", "Execution ID already binds a different Core resolution")
    references = {"music_plan": _ref(record), "music_annotation": document["annotation"]}
    if document["request"]["target"]["kind"] == "splice":
        references["music_replacement_annotation"] = document["replacement"]["annotation"]
    return {**result, **references}


def arrange(store: ArtifactStore, request):
    from .music_arrangement import arrange as create_arrangement
    return create_arrangement(store, request)


def extend_parser(parser):
    commands = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    music = commands.add_parser("music", help="Annotate existing audio and explicitly plan or execute musical regions.").add_subparsers(
        dest="music_command", required=True)
    for name in ("annotate", "plan", "arrange"):
        music.add_parser(name).add_argument("--request", type=Path, required=True)
    for name in ("show", "execute"):
        music.add_parser(name).add_argument("asset_id")


def handle_extra(args, store):
    if args.music_command in ("annotate", "plan", "arrange"):
        request = parse_json(stable_read(args.request, max_bytes=MAX_JSON_BYTES))
        return {"annotate": annotate, "plan": plan, "arrange": arrange}[args.music_command](store, request)
    return {"show": show, "execute": execute}[args.music_command](store, args.asset_id)
