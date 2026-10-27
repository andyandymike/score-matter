"""Explicit reuse of a published SA3 proposal; only Core PCM assembly runs."""
from __future__ import annotations

import argparse
from pathlib import Path

from matter_audio_core.actions import ActionService
from matter_audio_core.artifacts import Publication, stable_read
from matter_audio_core.contracts import (ACTION_SCHEMA, ASSET_PATTERN, MAX_JSON_BYTES, PROTECTION_REF,
                                        REQUEST_PATTERN, canonical, fingerprint, object_schema, parse_json, validate)
from matter_audio_core.composition import splice
from matter_audio_core.errors import AudioError
from matter_audio_core.fades import FRAME_COUNT
from matter_audio_core.media import decode_wav, trim

from .sa3_edit import PROFILE, RATE, SCHEMA as GENERATION_SCHEMA, SA3EditAdapter

OPERATION = "score.sa3_reassembly/v1"
DOCUMENT_SCHEMA = "score-sa3-reassembly-plan/v1"
PLAN_MEDIA = {"kind": "sa3_reassembly_plan", "content_type": "application/json"}
REQUEST_SCHEMA = object_schema({
    "schema": {"const": "score-sa3-reassembly/v1"},
    "request_id": {"type": "string", "pattern": REQUEST_PATTERN},
    "source_request_id": {"type": "string", "pattern": REQUEST_PATTERN},
    "base_asset_id": {"type": "string", "pattern": ASSET_PATTERN},
    "proposal_asset_id": {"type": "string", "pattern": ASSET_PATTERN},
    "assembly": {"oneOf": [
        object_schema({"transition_frames": FRAME_COUNT}),
        object_schema({"transition_frames": FRAME_COUNT, "start_frame": FRAME_COUNT, "end_frame": FRAME_COUNT}),
    ]},
    "protection": PROTECTION_REF,
}, ["schema", "request_id", "source_request_id", "base_asset_id", "proposal_asset_id", "assembly"])
LIMITATIONS = [
    "Reassembly performs zero new model inferences; it reuses the recorded proposal, not a cache of equivalent prompts.",
    "Only transitions and a narrower window inside the original allowed write range may change. New prompts, seeds, masks or generation settings require a new generation action.",
    "Recorded local provenance and PCM relationships are verified, not independently attested model execution, rights or listening acceptance.",
    "Results remain candidates; no session selection, feedback, new annotations or protection is created.",
]


def _ref(record):
    return {key: record[key] for key in ("asset_id", "digest", "media")}


def _mismatch(message):
    raise AudioError("proposal_source_mismatch", message)


def _source(store, request):
    """Verify the original receipt without resolving against today's SA3 runtime."""
    result = store.show_request(request["source_request_id"])
    if result["status"] != "succeeded":
        _mismatch("The source generation must have a completed successful result")
    try:
        resolution = result["resolution"]
        original = resolution["request"]
        validate(original, ACTION_SCHEMA)
        validate(original["parameters"], GENERATION_SCHEMA)
        if (original["operation"] != "score.sa3_inpaint/v1" or original["request_id"] != request["source_request_id"]
                or original["inputs"] != [request["base_asset_id"]] or resolution["profile"] != PROFILE
                or result["binding"] != {"resolution": resolution}
                or result["binding_digest"] != fingerprint(result["binding"])
                or resolution["digest"] != fingerprint({k: v for k, v in resolution.items() if k != "digest"})):
            _mismatch("The receipt does not bind this original SA3 action and base")
        outputs = result["outputs"]
        if len(outputs) != 2 or [item["role"] for item in outputs] != ["audio", "model_proposal"]:
            _mismatch("The source action must contain its final audio and unassembled model proposal")
        if outputs[1]["asset_id"] != request["proposal_asset_id"]:
            _mismatch("The proposal is not the original action's model_proposal output")
        base_record, base_data = store.asset(request["base_asset_id"])
        proposal_record, proposal_data = store.asset(request["proposal_asset_id"])
        final_record, final_data = store.asset(outputs[0]["asset_id"])
        if proposal_record != outputs[1] or final_record != outputs[0]:
            _mismatch("Source outputs differ from their published records")
        anchor = {"asset_id": base_record["asset_id"], "digest": base_record["digest"]}
        if (resolution["inputs"] != [anchor]
                or proposal_record["parents"] != [{"role": "context", **anchor}]
                or final_record["parents"] != [{"role": "source", **anchor}]
                or any(item["provenance"].get("operation") != original["operation"]
                       or item["provenance"].get("profile") != PROFILE for item in outputs)):
            _mismatch("Source input digests, parent references or operation profiles differ")
        base, proposal, final = map(decode_wav, (base_data, proposal_data, final_data))
        effective = resolution["effective_parameters"]
        if not isinstance(effective["backend"], dict) or not effective["backend"]:
            _mismatch("The generation's recorded backend identity is absent")
        expected = SA3EditAdapter.resolve_recorded(original["parameters"], base, effective["backend"])
        if effective != expected:
            _mismatch("Recorded generation parameters do not reconstruct from the original action")
        if ((proposal.sample_rate, proposal.channels) != (base.sample_rate, base.channels)
                or proposal.frames != effective["model_seconds"] * RATE):
            _mismatch("Proposal media differs from the original generation's output contract")
        aligned = trim(proposal, 0, base.frames) if proposal.frames != base.frames else proposal
        assembled, report = splice(effective["splice"], [base, aligned])
        if final != assembled:
            _mismatch("The original final audio is not the recorded proposal assembled onto this base")
        finding = result["findings"][0]
        if (finding["method"] != PROFILE or finding["source_asset_id"] != base_record["asset_id"]
                or finding["observed_changes"] != report["observed_changes"]
                or any(finding[key] != effective[key] for key in ("context_read", "requested_edit", "model_mask", "allowed_write"))):
            _mismatch("Recorded generation findings differ from the original PCM assembly")
    except (KeyError, IndexError, TypeError) as exc:
        raise AudioError("proposal_source_mismatch", "Incomplete or malformed original generation evidence") from exc
    return {"receipt": {"request_id": result["request_id"], "group_id": result["group_id"], "digest": fingerprint(result)},
            "resolution": resolution, "base": _ref(base_record), "proposal": _ref(proposal_record),
            "original_output": _ref(final_record)}


def _binding(store, request):
    validate(request, REQUEST_SCHEMA)
    source = _source(store, request)
    original_window = source["resolution"]["effective_parameters"]["requested_edit"]
    assembly = request["assembly"]
    start = assembly.get("start_frame", original_window["start_frame"])
    end = assembly.get("end_frame", original_window["end_frame"])
    if not original_window["start_frame"] <= start < end <= original_window["end_frame"]:
        raise AudioError("proposal_write_range", "Reassembly must stay inside the original allowed write window; generate anew to change the model mask")
    return {"operation": OPERATION, "request": request, "source": source,
            "assembly": {"start_frame": start, "end_frame": end, "replacement_start_frame": start,
                         "transition_frames": assembly["transition_frames"]}}


def _core_request(binding):
    request = {"schema": "matter-action/v1", "request_id": "proposal-" + fingerprint(binding)["hex"],
               "operation": "splice/v1", "inputs": [binding["source"]["base"]["asset_id"],
                                                       binding["source"]["proposal"]["asset_id"]],
               "parameters": binding["assembly"]}
    protection = binding["request"].get("protection", binding["source"]["resolution"]["request"].get("protection"))
    if protection is not None:
        request["protection"] = protection
    return request


def _document(binding, resolution):
    return {"schema": DOCUMENT_SCHEMA, "binding": binding, "core_request": _core_request(binding),
            "core_resolution": resolution, "expected_resolution_digest": resolution["digest"]["hex"],
            "reuse": {"reason": "Exact base and proposal from the same verified successful SA3 result; only PCM assembly changes",
                      "new_model_inferences": 0, "original_generation_unchanged": True,
                      "window": binding["assembly"]}}


def _parents(binding):
    return [{"role": role, "asset_id": binding["source"][role]["asset_id"],
             "digest": binding["source"][role]["digest"]} for role in ("base", "proposal", "original_output")]


def plan(store, request):
    binding = _binding(store, request)
    try:
        previous = store.show_request(request["request_id"])
    except AudioError as exc:
        if exc.code != "request_not_found":
            raise
    else:
        if previous["binding"] != binding:
            raise AudioError("request_conflict", "Plan request ID already binds another proposal or assembly")
        return previous
    resolution = ActionService(store).resolve(_core_request(binding))
    document = _document(binding, resolution)
    data = canonical(document)
    if len(data) > MAX_JSON_BYTES:
        raise AudioError("json_too_large", "Proposal plan exceeds 1 MiB")
    parents = _parents(binding)

    def produce(publication):
        output = publication.add(data, PLAN_MEDIA,
                                 role="sa3_reassembly_plan", parents=parents)
        return {"plan": output, "document": document, "limitations": LIMITATIONS}

    preview = Publication("0" * 32)
    store.validate_publication(request["request_id"], binding, preview, produce(preview))
    return store.transact(request["request_id"], binding, produce)


def _load(store, asset_id):
    record, raw = store.asset(asset_id)
    if record["role"] != "sa3_reassembly_plan":
        raise AudioError("invalid_proposal_plan", "Expected a saved SA3 reassembly plan")
    document = parse_json(raw)
    try:
        binding = _binding(store, document["binding"]["request"])
        if record["media"] != PLAN_MEDIA or record["parents"] != _parents(binding):
            raise AudioError("proposal_binding_mismatch", "Plan asset metadata does not retain its exact source parents")
        resolution = document["core_resolution"]
        if (document != _document(binding, resolution)
                or resolution["request"] != _core_request(binding)
                or resolution["digest"] != fingerprint({k: v for k, v in resolution.items() if k != "digest"})):
            raise AudioError("proposal_binding_mismatch", "Plan differs from the original evidence or frozen Core request")
        # Validate PCM semantics without consulting current protection. Completed
        # receipts remain readable after a session's locks have changed.
        unprotected = {k: v for k, v in resolution["request"].items() if k != "protection"}
        check = ActionService(store).resolve(unprotected)
        if any(resolution[k] != check[k] for k in ("schema", "inputs", "profile", "effective_parameters", "audio_model_calls", "unverified_goals")):
            raise AudioError("proposal_binding_mismatch", "Frozen splice resolution does not match the verified inputs")
    except (KeyError, TypeError) as exc:
        raise AudioError("invalid_proposal_plan", "Incomplete proposal plan") from exc
    return record, document


def show(store, asset_id):
    record, document = _load(store, asset_id)
    return {"schema": "score-sa3-reassembly-document/v1", "asset": record,
            "document": document, "audio_model_calls": 0}


def execute(store, asset_id):
    record, document = _load(store, asset_id)
    request = document["core_request"]
    try:
        result = store.show_request(request["request_id"])
    except AudioError as exc:
        if exc.code != "request_not_found":
            raise
        result = ActionService(store).execute(request, expected_resolution_digest=document["expected_resolution_digest"])
    else:
        if result["binding"] != {"resolution": document["core_resolution"]}:
            raise AudioError("request_conflict", "Execution ID already binds another splice resolution")
    return {**result, "proposal_plan": _ref(record), "reused_generation": document["binding"]["source"]["receipt"],
            "new_model_inferences": 0}


def capabilities():
    return {"proposal_reassembly": {"availability": "available", "commands": ["proposal plan", "proposal show", "proposal execute"],
            "file_parameters": {"proposal plan": ["--request"]}, "request_schema": REQUEST_SCHEMA,
            "document_schema": DOCUMENT_SCHEMA, "limitations": LIMITATIONS}}


def extend_parser(parser):
    commands = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    proposals = commands.add_parser("proposal", help="Plan explicit reuse of an existing SA3 model proposal.").add_subparsers(
        dest="proposal_command", required=True)
    proposals.add_parser("plan").add_argument("--request", type=Path, required=True)
    for name in ("show", "execute"):
        proposals.add_parser(name).add_argument("asset_id")


def handle_extra(args, store):
    if args.proposal_command == "plan":
        return plan(store, parse_json(stable_read(args.request, max_bytes=MAX_JSON_BYTES)))
    return {"show": show, "execute": execute}[args.proposal_command](store, args.asset_id)
