"""Explicit frame annotations over a verified, already executed arrangement."""
from __future__ import annotations

from matter_audio_core.artifacts import ArtifactStore
from matter_audio_core.contracts import object_schema, parse_json, validate
from matter_audio_core.errors import AudioError

from .music import ASSET_ID, IDENTIFIER, ROUNDING, _audio, _ref, resolve_position
from .music_arrangement import _publication_budget, load as load_arrangement
from .music_validation import MAX_ANCESTRY, derived_annotation_level, validation_scope


DOCUMENT_SCHEMA = "score-music-arrangement-annotation/v1"
REGION_SCHEMA = object_schema({"id": IDENTIFIER, "segment_id": IDENTIFIER,
    "repeat_index": {"type": "integer", "minimum": 0, "maximum": 63}, "range": {"enum": ["full", "body"]}})
ANNOTATE_ARRANGEMENT_SCHEMA = object_schema({"schema": {"const": "score-music-annotate-arrangement/v1"},
    "request_id": IDENTIFIER, "plan_id": ASSET_ID, "source": {"enum": ["user", "agent", "project", "unknown"]},
    "regions": {"type": "array", "minItems": 1, "maxItems": 128, "items": REGION_SCHEMA}})
LIMITATIONS = [
    "Annotations require an already completed, matching arrangement action; creating them never executes an action.",
    "Full ranges include transition mixtures. Bodies exclude the complete overlap windows and must remain nonempty.",
    "Timing is unknown; source tempo grids, locks, selection and feedback are not inherited.",
    "Source is a supplied annotation declaration, not a new listening judgment or verified musical quality.",
    "Each request names at most 128 distinct occurrences. Derived annotation ancestry is limited to 32 active levels.",
]


@validation_scope()
def _build(store, request):
    validate(request, ANNOTATE_ARRANGEMENT_SCHEMA)
    ids, occurrences = set(), set()
    for item in request["regions"]:
        if item["id"] in ids:
            raise AudioError("duplicate_music_region", "Region IDs must be unique")
        key = (item["segment_id"], item["repeat_index"])
        if key in occurrences:
            raise AudioError("duplicate_music_occurrence", "An occurrence may be annotated only once per request")
        ids.add(item["id"])
        occurrences.add(key)
    plan_record, plan = load_arrangement(store, request["plan_id"])
    try:
        result = store.show_request(plan["core_request"]["request_id"])
    except AudioError as exc:
        if exc.code != "request_not_found":
            raise
        raise AudioError("music_arrangement_not_completed", "Execute this arrangement explicitly before annotating its output") from exc
    if result["binding"] != {"resolution": plan["core_resolution"]}:
        raise AudioError("music_binding_mismatch", "Arrangement action receipt binds a different Core resolution")
    if result["status"] != "succeeded" or len(result["outputs"]) != 1:
        raise AudioError("music_arrangement_not_completed", "Arrangement action must have completed with one audio output")
    audio = _audio(store, result["outputs"][0]["asset_id"])
    if (audio["media"]["frame_count"] != plan["duration_frames"]
            or any(audio["media"][key] != plan["inputs"][0]["media"][key] for key in ("channels", "sample_rate_hz"))):
        raise AudioError("music_binding_mismatch", "Completed output does not match the arrangement's frozen media contract")
    execution = {key: result[key] for key in ("request_id", "group_id", "binding_digest")}
    execution["resolution_digest"] = plan["expected_resolution_digest"]
    timeline = {(item["segment_id"], item["repeat_index"]): item for item in plan["timeline"]}
    resolved, mappings = [], []
    timing = {"mode": "unknown"}
    for region in request["regions"]:
        occurrence = timeline.get((region["segment_id"], region["repeat_index"]))
        if occurrence is None:
            raise AudioError("music_occurrence_not_found", "Requested occurrence is absent from this exact arrangement")
        incoming, outgoing = occurrence.get("fade_in_frames", 0), occurrence.get("fade_out_frames", 0)
        start, end = occurrence["start_frame"], occurrence["end_frame"]
        if region["range"] == "body":
            start, end = start + incoming, end - outgoing
            if start >= end:
                raise AudioError("music_empty_body", "This occurrence has no frames outside its transition windows")
        segment = plan["segments"][occurrence["segment_index"]]
        resolved.append({"id": region["id"], "start": resolve_position({"frame": start}, timing, audio["media"]),
            "end": resolve_position({"frame": end}, timing, audio["media"]), "start_frame": start, "end_frame": end})
        mappings.append({"id": region["id"], "segment_id": region["segment_id"], "repeat_index": region["repeat_index"],
            "range": region["range"], "annotation": segment["annotation"], "audio": segment["audio"],
            "source_region": segment["region"],
            "source_start_frame": segment["region"]["start_frame"] + start - occurrence["start_frame"],
            "source_end_frame": segment["region"]["start_frame"] + end - occurrence["start_frame"],
            "output_start_frame": start, "output_end_frame": end,
            "contains_transition": region["range"] == "full" and bool(incoming or outgoing)})
    document = {"schema": DOCUMENT_SCHEMA, "request": request, "plan": _ref(plan_record), "execution": execution,
        "audio": audio, "timing": timing, "resolved_regions": resolved, "mappings": mappings, "rounding": ROUNDING}
    parents = [{"role": "annotates", **_ref(audio)}, {"role": "arrangement_plan", **_ref(plan_record)}]
    binding = {"operation": "score.music.annotate_arrangement/v1", "document": document}
    data = _publication_budget(store, binding, document, parents, LIMITATIONS)
    return binding, document, parents, data


def annotate_arrangement(store: ArtifactStore, request):
    # Reserve the new annotation's own level before claiming its publication.
    with derived_annotation_level():
        binding, document, parents, data = _build(store, request)

    def produce(publication):
        output = publication.add(data, {"kind": "music_annotation", "content_type": "application/json"},
                                 role="music_annotation", parents=parents)
        return {"annotation": output, "document": document, "limitations": LIMITATIONS}

    return store.transact(request["request_id"], binding, produce)


def load(store: ArtifactStore, asset_id):
    with derived_annotation_level():
        record, raw = store.asset(asset_id)
        document = parse_json(raw)
        if (record["role"] != "music_annotation" or not isinstance(document, dict)
                or document.get("schema") != DOCUMENT_SCHEMA):
            raise AudioError("invalid_music_annotation", "Expected an arrangement annotation")
        _, rebuilt, parents, _ = _build(store, document.get("request"))
        if document != rebuilt or record["parents"] != parents:
            raise AudioError("music_binding_mismatch", "Annotation differs from its completed arrangement or occurrence mapping")
        return record, document
