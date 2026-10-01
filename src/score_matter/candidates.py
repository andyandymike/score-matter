"""Register existing music candidates without generating or selecting audio."""
from __future__ import annotations

import argparse
from pathlib import Path

from matter_audio_core.artifacts import ArtifactStore, safe_path, stable_read
from matter_audio_core.contracts import MAX_JSON_BYTES, REQUEST_PATTERN, digest, object_schema, parse_json, validate
from matter_audio_core.errors import AudioError
from matter_audio_core.media import decode_wav


PROFILE = "score.register_candidate/v1"
TEXT = {"type": "string", "minLength": 1, "maxLength": 4000, "pattern": r"\S"}
INTENT_SCHEMA = object_schema({
    "schema": {"const": "score-music-intent/v1"},
    "source": {"enum": ["user", "agent", "project", "unknown"]},
    "purpose": TEXT,
    "preserve": {"type": "array", "maxItems": 32, "items": TEXT},
    "change": {"type": "array", "maxItems": 32, "items": TEXT},
    "notes": TEXT,
}, ["schema", "source", "purpose"])

# Legacy generation records have no versioned schema. Validate only the binding
# fields; retain all original bytes and historical claims without endorsing them.
GENERATION_RECORD_SCHEMA = {
    "type": "object", "required": ["kind", "status", "output"],
    "properties": {
        "kind": {"const": "score-matter-fast-generation"},
        "status": {"const": "candidate"},
        "output": {
            "type": "object", "required": ["sha256", "media"],
            "properties": {
                "sha256": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
                "media": {
                    "type": "object",
                    "required": ["container", "codec", "sample_rate_hz", "channels", "sample_width_bytes", "frame_count"],
                    "properties": {
                        "container": {"const": "wav"}, "codec": {"const": "pcm_s16le"},
                        "sample_rate_hz": {"type": "integer", "minimum": 1},
                        "channels": {"type": "integer", "minimum": 1},
                        "sample_width_bytes": {"const": 2},
                        "frame_count": {"type": "integer", "minimum": 1},
                    },
                },
            },
        },
    },
}
LIMITATIONS = [
    "Registration calls no model and does not create or select a session.",
    "A supplied generation record is checked against audio bytes and media facts only; its historical claims and model weights are not verified.",
    "Without a generation record, audio origin remains unknown.",
    "Music intent records desired authoring choices, not listening feedback, musical consistency or approval.",
    "Registration does not establish distribution rights.",
    "An incomplete core request claim remains recovery_pending; registration never regenerates audio or retries under a new ID.",
]


def capabilities():
    return {"candidate_registration": {
        "availability": "available", "command": "candidate register", "profile": PROFILE,
        "file_parameters": ["--audio", "--generation-record", "--intent"],
        "required_parameters": ["--audio", "--request-id"],
        "intent_schema": INTENT_SCHEMA, "generation_record_binding_schema": GENERATION_RECORD_SCHEMA,
        "result_schema": "matter-result/v1", "audio_output_index": 0,
        "attachment_roles": ["generation_record", "music_intent"],
        "validation": ["stable bounded input snapshots", "generation record SHA-256 and PCM media match",
                       "strict JSON and music intent schema", "complete immutable publication"],
        "limitations": LIMITATIONS,
    }}


def _json_snapshot(path):
    raw = stable_read(path, max_bytes=MAX_JSON_BYTES)
    return raw, parse_json(raw)


def register_candidate(store: ArtifactStore, audio: Path, request_id: str, *,
                       generation_record: Path | None = None, intent: Path | None = None):
    validate(request_id, {"type": "string", "pattern": REQUEST_PATTERN})
    if generation_record is None and intent is None:
        return store.import_wav(audio, request_id)

    data = stable_read(audio)
    pcm = decode_wav(data)
    audio_digest = digest(data)
    attachments = []
    if generation_record is not None:
        raw, record = _json_snapshot(generation_record)
        validate(record, GENERATION_RECORD_SCHEMA)
        observed = {key: pcm.facts()[key] for key in (
            "container", "codec", "sample_rate_hz", "channels", "frame_count")}
        observed["sample_width_bytes"] = 2
        mismatches = {key: {"recorded": record["output"]["media"][key], "observed": value}
                      for key, value in observed.items() if record["output"]["media"][key] != value}
        expected_hash = "sha256:" + audio_digest["hex"]
        if record["output"]["sha256"] != expected_hash:
            mismatches["sha256"] = {"recorded": record["output"]["sha256"], "observed": expected_hash}
        if mismatches:
            raise AudioError("generation_record_mismatch", "Generation record does not match the supplied WAV",
                             details=mismatches)
        attachments.append(("generation_record", raw))
    if intent is not None:
        raw, document = _json_snapshot(intent)
        validate(document, INTENT_SCHEMA)
        attachments.append(("music_intent", raw))

    attachment_digests = {role: digest(raw) for role, raw in attachments}
    binding = {"operation": PROFILE, "audio_digest": audio_digest,
               "attachments": attachment_digests}
    provenance = {"kind": "score_candidate_registration", "source_path": str(safe_path(audio)),
                  "origin": "unverified_generation_record" if generation_record is not None else "unknown",
                  "rights": "unknown", "attachments": attachment_digests}

    def produce(publication):
        registered = publication.add(data, pcm.facts(), provenance=provenance)
        for role, raw in attachments:
            publication.add(raw, {"kind": role, "content_type": "application/json"}, role=role,
                            parents=[{"role": "describes", "asset_id": registered["asset_id"],
                                      "digest": registered["digest"]}])
        return {"findings": [{"kind": "measurement", "method": PROFILE,
                              "generation_record_binding": "sha256_and_media_match" if generation_record is not None else "absent"}],
                "limitations": LIMITATIONS}

    return store.transact(request_id, binding, produce)


def extend_parser(parser):
    commands = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    candidates = commands.add_parser("candidate", help="Register existing music candidates.").add_subparsers(
        dest="candidate_command", required=True)
    registering = candidates.add_parser("register", help="Snapshot a WAV and optional generation record/music intent; never generate or select.")
    registering.add_argument("--audio", type=Path, required=True, help="Existing PCM16 WAV to snapshot.")
    registering.add_argument("--generation-record", type=Path, help="Existing ScoreMatter generation record to bind and preserve.")
    registering.add_argument("--intent", type=Path, help="Optional score-music-intent/v1 JSON; not listening feedback.")
    registering.add_argument("--request-id", required=True)


def handle_extra(args, store):
    if args.command != "candidate" or args.candidate_command != "register":
        raise AudioError("unsupported_command", args.command)
    return register_candidate(store, args.audio, args.request_id,
                              generation_record=args.generation_record, intent=args.intent)
