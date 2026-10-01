"""Sequential, frame-exact arrangements compiled to existing Core scene actions."""
from __future__ import annotations

from matter_audio_core.actions import ActionService
from matter_audio_core.artifacts import ArtifactStore
from matter_audio_core.contracts import MAX_JSON_BYTES, fingerprint, object_schema, parse_json, validate
from matter_audio_core.errors import AudioError
from matter_audio_core.fades import FRAME_COUNT

from .music import ASSET_ID, IDENTIFIER, _load_annotation, _ref
from .music_publication import validated_producer
from .music_validation import checked_asset, validation_scope


ROLE = "music_arrangement"
DOCUMENT_SCHEMA = "score-music-arrangement-plan/v1"
LIMITS = {"segments": 128, "repeat": 64, "occurrences": 1024, "distinct_audio": 16, "parents": 144,
          "input_wav_bytes": 64 * 1024 * 1024, "output_wav_bytes": 64 * 1024 * 1024,
          "publication_json_bytes": MAX_JSON_BYTES}
SEGMENT_SCHEMA = object_schema({"id": IDENTIFIER, "annotation_id": ASSET_ID, "region_id": IDENTIFIER,
                                "repeat": {"type": "integer", "minimum": 1, "maximum": LIMITS["repeat"]}})
ARRANGE_SCHEMA = object_schema({"schema": {"const": "score-music-arrange/v1"}, "request_id": IDENTIFIER,
    "segments": {"type": "array", "minItems": 1, "maxItems": LIMITS["segments"], "items": SEGMENT_SCHEMA}})
TRANSITION_SCHEMA = object_schema({"after_segment_id": IDENTIFIER,
    "after_repeat_index": {"type": "integer", "minimum": 0, "maximum": 63},
    "crossfade_frames": {**FRAME_COUNT, "minimum": 2}})
ARRANGE_V2_SCHEMA = object_schema({"schema": {"const": "score-music-arrange/v2"}, "request_id": IDENTIFIER,
    "segments": ARRANGE_SCHEMA["properties"]["segments"],
    "transitions": {"type": "array", "maxItems": 1023, "items": TRANSITION_SCHEMA}})
ARRANGE_REQUEST_SCHEMA = {"oneOf": [ARRANGE_SCHEMA, ARRANGE_V2_SCHEMA]}
DOCUMENT_V2_SCHEMA = "score-music-arrangement-plan/v2"
LIMITATIONS = [
    "Arrangement copies named regions sequentially with integer repeats; it does not infer a global tempo or align beats.",
    "No gaps, overlaps, fades, padding, resampling or time stretching are added.",
    "The output is a new timeline. Source annotations and PCM locks are not inherited; protection/session fields are rejected.",
    "Planning and execution do not select audio, change source sessions or add feedback. Use a separate explicit session workflow.",
    "New annotations or locks require an explicit request. Exact copying does not establish musical or listening acceptance.",
    "An interrupted Core action claim remains recovery_pending; no new ID or regeneration is attempted.",
]
V2_LIMITATIONS = [
    "Only explicitly named adjacent occurrences overlap, using Core's linear Q24 envelopes and clipping rejection.",
    "Crossfades shorten the output by their frame counts; bodies exclude the complete incoming and outgoing overlap windows.",
    "There is no beat alignment, time stretching, resampling, global tempo inference or automatic listening approval.",
    *LIMITATIONS[2:],
]


def _transition_timeline(request, segments, original):
    positions = {(item["segment_id"], item["repeat_index"]): index for index, item in enumerate(original)}
    boundaries = {}
    for transition in request["transitions"]:
        index = positions.get((transition["after_segment_id"], transition["after_repeat_index"]))
        if index is None or index == len(original) - 1:
            raise AudioError("music_transition_boundary", "Transition must follow an existing non-final occurrence")
        if index in boundaries:
            raise AudioError("duplicate_music_transition", "Each occurrence boundary accepts only one transition")
        boundaries[index] = transition["crossfade_frames"]
    timeline, cursor = [], 0
    for index, item in enumerate(original):
        incoming, outgoing = boundaries.get(index - 1, 0), boundaries.get(index, 0)
        length = item["end_frame"] - item["start_frame"]
        if incoming + outgoing > length:
            raise AudioError("music_transition_overlap", "Incoming and outgoing transitions must fit without overlapping")
        start = cursor - incoming
        cursor = start + length
        timeline.append({**item, "start_frame": start, "end_frame": cursor,
                         "fade_in_frames": incoming, "fade_out_frames": outgoing,
                         "body_start_frame": start + incoming, "body_end_frame": cursor - outgoing})
    transitions = []
    for index, frames in sorted(boundaries.items()):
        left, right = timeline[index], timeline[index + 1]
        transitions.append({"after_segment_id": left["segment_id"], "after_repeat_index": left["repeat_index"],
            "before_segment_id": right["segment_id"], "before_repeat_index": right["repeat_index"],
            "crossfade_frames": frames, "start_frame": right["start_frame"], "end_frame": left["end_frame"]})
    events = []
    group_segment = None
    for item in timeline:
        segment = segments[item["segment_index"]]
        length = item["end_frame"] - item["start_frame"]
        previous = events[-1] if events else None
        if (previous is not None and group_segment == item["segment_index"] and previous["repeat"] < 64
                and previous["fade_in_frames"] == item["fade_in_frames"]
                and previous["fade_out_frames"] == item["fade_out_frames"]):
            interval = item["start_frame"] - previous["offset_frame"] if previous["repeat"] == 1 else previous["interval_frames"]
            if interval > 0 and item["start_frame"] == previous["offset_frame"] + previous["repeat"] * interval:
                previous["interval_frames"] = interval
                previous["repeat"] += 1
                continue
        if len(events) == 128:
            raise AudioError("music_arrangement_event_limit", "Explicit transition pattern needs more than 128 Core event definitions")
        events.append({"event_id": f"event-{len(events)}", "input_index": segment["input_index"], "track": "music",
            "source_start_frame": segment["region"]["start_frame"], "source_end_frame": segment["region"]["end_frame"],
            "offset_frame": item["start_frame"], "repeat": 1, "interval_frames": length, "db": 0,
            "fade_in_frames": item["fade_in_frames"], "fade_out_frames": item["fade_out_frames"]})
        group_segment = item["segment_index"]
    return timeline, transitions, events, cursor


@validation_scope()
def _build(store, request):
    validate(request, ARRANGE_REQUEST_SCHEMA)
    v2 = request["schema"] == "score-music-arrange/v2"
    ids = [segment["id"] for segment in request["segments"]]
    if len(set(ids)) != len(ids):
        raise AudioError("duplicate_music_segment", "Arrangement segment IDs must be unique")
    if sum(segment["repeat"] for segment in request["segments"]) > LIMITS["occurrences"]:
        raise AudioError("music_arrangement_limit", "Arrangement exceeds 1024 occurrences")
    annotation_cache, source_indices = {}, {}
    segments, inputs, timeline, events, parents = [], [], [], [], []
    cursor = 0
    for index, segment in enumerate(request["segments"]):
        annotation_id = segment["annotation_id"]
        if annotation_id not in annotation_cache:
            annotation_cache[annotation_id] = _load_annotation(store, annotation_id)
            parents.append({"role": "annotation", **_ref(annotation_cache[annotation_id][0])})
        record, annotation = annotation_cache[annotation_id]
        region = next((item for item in annotation["resolved_regions"] if item["id"] == segment["region_id"]), None)
        if region is None:
            raise AudioError("music_region_not_found", "Arrangement region is absent from this exact annotation")
        audio = annotation["audio"]
        if inputs and any(audio["media"][key] != inputs[0]["media"][key] for key in ("sample_rate_hz", "channels")):
            raise AudioError("music_arrangement_format_mismatch", "All arrangement inputs must share sample rate and channels")
        if audio["asset_id"] not in source_indices:
            if len(inputs) >= LIMITS["distinct_audio"]:
                raise AudioError("music_arrangement_limit", "Arrangement exceeds 16 distinct audio assets")
            source_indices[audio["asset_id"]] = len(inputs)
            inputs.append(audio)
        input_index = source_indices[audio["asset_id"]]
        segments.append({"id": segment["id"], "repeat": segment["repeat"], "annotation": _ref(record),
                         "audio": audio, "region": region, "input_index": input_index})
        length = region["end_frame"] - region["start_frame"]
        # Core event keys have a narrower alphabet/length than musical segment IDs.
        events.append({"event_id": f"segment-{index}", "input_index": input_index, "track": "music",
                       "source_start_frame": region["start_frame"], "source_end_frame": region["end_frame"],
                       "offset_frame": cursor, "repeat": segment["repeat"], "interval_frames": length,
                       "db": 0, "fade_in_frames": 0, "fade_out_frames": 0})
        for repeat_index in range(segment["repeat"]):
            start = cursor + repeat_index * length
            timeline.append({"segment_index": index, "segment_id": segment["id"], "repeat_index": repeat_index,
                             "start_frame": start, "end_frame": start + length})
        cursor += length * segment["repeat"]
    parents.extend({"role": "source", **_ref(audio)} for audio in inputs)
    if len(parents) > LIMITS["parents"]:
        raise AudioError("music_arrangement_limit", "Arrangement exceeds its parent reference limit")
    if v2:
        timeline, transitions, events, cursor = _transition_timeline(request, segments, timeline)
    binding = {"operation": "score.music.arrange/v2" if v2 else "score.music.arrange/v1",
               "request": request, "segments": segments, "inputs": inputs}
    core_request = {"schema": "matter-action/v1", "request_id": "music-" + fingerprint(binding)["hex"],
                    "operation": "scene/v1", "inputs": [audio["asset_id"] for audio in inputs],
                    "parameters": {"duration_frames": cursor, "tracks": [{"name": "music", "db": 0,
                        "fade_in_frames": 0, "fade_out_frames": 0}], "events": events, "master_db": 0, "clip": "reject"}}
    # This checks complete input WAV sizes and the output limit, without rendering.
    resolution = ActionService(store).resolve(core_request)
    document = {"schema": DOCUMENT_V2_SCHEMA if v2 else DOCUMENT_SCHEMA, "request": request, "segments": segments, "inputs": inputs,
                "timeline": timeline, "duration_frames": cursor, "core_request": core_request,
                "core_resolution": resolution, "expected_resolution_digest": resolution["digest"]["hex"]}
    if v2:
        document.update({"transitions": transitions, "transition_curve": "linear", "envelope_profile": "q24",
                         "shortened_by_frames": sum(item["crossfade_frames"] for item in transitions)})
    produce = validated_producer(store, request["request_id"], binding, document, ROLE, parents,
                                 V2_LIMITATIONS if v2 else LIMITATIONS)
    return binding, document, parents, produce


def arrange(store: ArtifactStore, request):
    binding, _, _, produce = _build(store, request)
    return store.transact(request["request_id"], binding, produce)


@checked_asset("arrangement")
def load(store: ArtifactStore, asset_id):
    record, raw = store.asset(asset_id)
    if record["role"] != ROLE:
        raise AudioError("invalid_music_arrangement", "Expected a saved music arrangement plan")
    document = parse_json(raw)
    if not isinstance(document, dict) or document.get("schema") not in (DOCUMENT_SCHEMA, DOCUMENT_V2_SCHEMA):
        raise AudioError("invalid_music_arrangement", "Expected a saved music arrangement plan")
    _, rebuilt, parents, _ = _build(store, document["request"])
    if document != rebuilt or record["parents"] != parents:
        raise AudioError("music_binding_mismatch", "Arrangement differs from its exact sources, sequence or frozen Core resolution")
    return record, document


def execute(store: ArtifactStore, asset_id):
    record, document = load(store, asset_id)
    request = document["core_request"]
    try:
        result = store.show_request(request["request_id"])
    except AudioError as exc:
        if exc.code != "request_not_found":
            raise
        result = ActionService(store).execute(request, expected_resolution_digest=document["expected_resolution_digest"])
    else:
        if result["binding"] != {"resolution": document["core_resolution"]}:
            raise AudioError("request_conflict", "Arrangement execution ID already binds a different Core resolution")
    annotations = []
    seen = set()
    for segment in document["segments"]:
        if segment["annotation"]["asset_id"] not in seen:
            annotations.append(segment["annotation"])
            seen.add(segment["annotation"]["asset_id"])
    return {**result, "music_plan": _ref(record), "music_annotations": annotations}
