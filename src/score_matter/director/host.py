from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from score_matter.canonical import (
    canonical_bytes,
    canonical_sha256,
    load_json_bytes,
    sha256_bytes,
    write_canonical_no_replace,
)
from score_matter.contracts import validate_document
from score_matter.errors import DirectorError, ScoreMatterError
from score_matter.providers.base import format_timestamp

from .adjudicator import AdjudicationResult, adjudicate_phase_a_case
from .compiler import CompiledDirectorArtifacts, compile_agent_response
from .evidence import DirectorEvidenceFile, DirectorEvidenceStore
from .policy import POLICY_SHA256, POLICY_TEXT, POLICY_VERSION


HOST_RESPONSE_CAPTURE_MAX_BYTES = 512 * 1024


@dataclass(frozen=True)
class HostIngestEvidence:
    """Immutable diagnostic receipt for one externally produced response."""

    document: dict[str, Any]
    file: DirectorEvidenceFile


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def build_host_agent_request(
    *,
    run_id: str,
    context: dict[str, Any],
    provider_descriptor: dict[str, Any],
    evidence_root: Path | str,
    ingest_claim_path: Path | str,
) -> dict[str, Any]:
    """Build the exact packet intentionally submitted to a host agent.

    The packet is not the host's complete model-visible request: ScoreMatter
    cannot observe a host's system instructions, history, routing, or tools.
    """

    context_snapshot = _snapshot(context)
    descriptor_snapshot = _snapshot(provider_descriptor)
    validate_document(context_snapshot, expected_schema="score-director-context/v1")
    validate_document(
        descriptor_snapshot, expected_schema="score-provider-descriptor/v1"
    )
    descriptor_sha256 = canonical_sha256(descriptor_snapshot)
    if context_snapshot["provider_descriptor_sha256"] != descriptor_sha256:
        raise DirectorError(
            "host request context binds a different provider descriptor",
            code="director_component_mismatch",
        )
    frozen_evidence_root = Path(evidence_root).resolve(strict=False)
    frozen_claim_path = Path(ingest_claim_path).resolve(strict=False)
    if frozen_evidence_root.exists() or frozen_evidence_root.is_symlink():
        raise DirectorError(
            "host request requires a fresh, nonexistent evidence_root",
            code="director_host_path_invalid",
        )
    if frozen_claim_path.exists() or frozen_claim_path.is_symlink():
        raise DirectorError(
            "host request requires a fresh, nonexistent ingest claim path",
            code="director_host_ingest_already_claimed",
        )
    request = {
        "schema": "score-director-host-request/v1",
        "run_id": run_id,
        "evidence_root": str(frozen_evidence_root),
        "ingest_claim_path": str(frozen_claim_path),
        "policy": {
            "version": POLICY_VERSION,
            "sha256": POLICY_SHA256,
            "text": POLICY_TEXT,
        },
        "context": context_snapshot,
        "provider_descriptor": descriptor_snapshot,
        "response_schema": "score-director-agent-response/v1",
        "capture": {
            "schema": "score-director-host-submission/v1",
            "applied_by": "operator_or_host_capture",
            "host_output": "bare_agent_response",
            "max_response_bytes": HOST_RESPONSE_CAPTURE_MAX_BYTES,
        },
        "phase_constraints": {
            "allowed_tools": [],
            "generator_calls": 0,
            "critic_calls": 0,
            "reference_audio_reader_calls": 0,
            "max_clarification_rounds": 1,
            "max_questions": 3,
            "grants_no_approval_authority": True,
        },
        "assurance_notice": {
            "submission_mode": "external_host_agent",
            "kernel_invokes_model": False,
            "complete_model_visible_context_verified": False,
            "capability_pass_eligible": False,
        },
    }
    return validate_host_agent_request(request)


def validate_host_agent_request(request: dict[str, Any]) -> dict[str, Any]:
    """Validate and return a detached canonical snapshot of a host packet."""

    snapshot = _snapshot(request)
    validate_document(snapshot, expected_schema="score-director-host-request/v1")
    if snapshot["policy"] != {
        "version": POLICY_VERSION,
        "sha256": POLICY_SHA256,
        "text": POLICY_TEXT,
    }:
        raise DirectorError(
            "host request does not contain the exact runtime Director policy",
            code="director_policy_mismatch",
        )
    _host_bound_paths(snapshot)
    return snapshot


def build_host_agent_submission(
    *,
    request: dict[str, Any],
    raw_response: bytes,
    submission_id: str,
    host_product: str,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Wrap exact bare host bytes without parsing or inventing observations."""

    request_snapshot = validate_host_agent_request(request)
    if not isinstance(raw_response, bytes):
        raise DirectorError(
            "host response capture requires bytes",
            code="director_protocol_invalid",
        )
    if len(raw_response) > HOST_RESPONSE_CAPTURE_MAX_BYTES:
        raise DirectorError(
            "host response exceeds the capture ceiling of "
            f"{HOST_RESPONSE_CAPTURE_MAX_BYTES} bytes",
            code="director_host_response_too_large",
        )
    submission = {
        "schema": "score-director-host-submission/v1",
        "submission_id": submission_id,
        "run_id": request_snapshot["run_id"],
        "request_sha256": canonical_sha256(request_snapshot),
        "host_disclosure": {
            "host_product": host_product,
            "host_version": None,
            "model_id": None,
            "model_revision": None,
            "identity_observation": "unavailable",
            "settings_observation": "unavailable",
            "usage_observation": "unavailable",
            "tool_observation": "unavailable",
            "complete_context_observation": "unavailable",
            "hidden_adjudication_isolation": "not_verified",
            "single_inference": "not_verified",
        },
        "usage": _unavailable_usage(),
        "observed_tool_calls": [],
        "response_capture": {
            "encoding": "base64",
            "media_type": "application/json",
            "raw_sha256": sha256_bytes(raw_response),
            "raw_byte_count": len(raw_response),
            "data_base64": base64.b64encode(raw_response).decode("ascii"),
        },
        "captured_at": format_timestamp(captured_at or utc_now()),
    }
    validate_document(
        submission, expected_schema="score-director-host-submission/v1"
    )
    return submission


def ingest_host_agent_submission(
    *,
    request: dict[str, Any],
    raw_submission: bytes,
    evidence_store: DirectorEvidenceStore,
    adjudication: dict[str, Any] | None = None,
    reported_at: datetime | None = None,
) -> HostIngestEvidence:
    """Retain and validate one existing host response without calling a model.

    A valid receipt proves only that exact submitted bytes were bound to the
    exact packet, accepted by the strict compiler, and optionally checked
    against one hidden adjudication. It is always capability-pass-ineligible.
    """

    request_snapshot = validate_host_agent_request(request)
    run_id = request_snapshot["run_id"]
    context = request_snapshot["context"]
    provider_descriptor = request_snapshot["provider_descriptor"]
    evidence_root, _claim_path = _host_bound_paths(request_snapshot)
    if evidence_store.root != evidence_root:
        raise DirectorError(
            "host ingest evidence store differs from the request-bound root",
            code="director_evidence_root_mismatch",
        )
    adjudication_snapshot: dict[str, Any] | None = None
    if adjudication is not None:
        adjudication_snapshot = _snapshot(adjudication)
        validate_document(
            adjudication_snapshot,
            expected_schema="score-director-adjudication/v1",
        )
        if adjudication_snapshot["context_sha256"] != canonical_sha256(context):
            raise DirectorError(
                "host ingest adjudication binds a different context",
                code="director_adjudication_mismatch",
            )
        if adjudication_snapshot["scenario_id"] != context["scenario_id"]:
            raise DirectorError(
                "host ingest adjudication scenario differs from the context",
                code="director_adjudication_mismatch",
            )

    moment = reported_at or utc_now()
    claim = _claim_host_ingest(
        request=request_snapshot,
        raw_submission=raw_submission,
        adjudication=adjudication_snapshot,
        claimed_at=moment,
    )
    claim_sha256 = canonical_sha256(claim)
    request_file = evidence_store.publish_json(run_id, "request", request_snapshot)
    retained_submission = _bounded_raw_payload(raw_submission, "host_submission")
    submission_file = evidence_store.publish_bytes(
        run_id, "host-submission", retained_submission
    )

    submission_json_valid = False
    submission_schema_valid = False
    request_binding_matched = False
    response_json_valid = False
    response_schema_valid = False
    semantic_valid: bool | None = None
    errors: list[dict[str, str]] = []
    artifacts: CompiledDirectorArtifacts | None = None
    adjudicated: AdjudicationResult | None = None
    submission: dict[str, Any] | None = None
    raw_response: bytes | None = None
    raw_response_file: DirectorEvidenceFile | None = None
    untrusted_response: dict[str, Any] | None = None
    disclosure = _unavailable_disclosure()
    usage = _unavailable_usage()
    conclusion = "submission_rejected"

    try:
        loaded = load_json_bytes(raw_submission, source="host-agent-submission")
        submission_json_valid = True
        if not isinstance(loaded, dict):
            raise DirectorError(
                "host submission must be a JSON object",
                code="director_protocol_invalid",
            )
        submission = loaded
        validate_document(
            submission, expected_schema="score-director-host-submission/v1"
        )
        submission_schema_valid = True
        disclosure = {
            name: submission["host_disclosure"][name]
            for name in (
                "identity_observation",
                "settings_observation",
                "usage_observation",
                "tool_observation",
            )
        }
        usage = dict(submission["usage"])
        if submission["run_id"] != run_id:
            raise DirectorError(
                "host submission run_id differs from the request",
                code="director_host_binding_mismatch",
            )
        if submission["request_sha256"] != request_file.sha256:
            raise DirectorError(
                "host submission binds a different request",
                code="director_host_binding_mismatch",
            )
        request_binding_matched = True
        raw_response = _decode_response_capture(submission["response_capture"])
        retained_response = _bounded_raw_payload(raw_response, "host_response")
        raw_response_file = evidence_store.publish_bytes(
            run_id, "raw-response", retained_response
        )
        if submission["observed_tool_calls"]:
            raise DirectorError(
                "host submission reports a forbidden tool call",
                code="director_tool_call_forbidden",
            )
        loaded_response = load_json_bytes(
            raw_response, source="captured-host-agent-response"
        )
        response_json_valid = True
        if not isinstance(loaded_response, dict):
            raise DirectorError(
                "host agent response must be a JSON object",
                code="director_protocol_invalid",
            )
        untrusted_response = loaded_response
        artifacts = compile_agent_response(
            run_id=run_id,
            context=context,
            provider_descriptor=provider_descriptor,
            response=untrusted_response,
        )
        response_schema_valid = True
        if adjudication_snapshot is None:
            conclusion = "diagnostic_contract_validated"
        else:
            adjudicated = adjudicate_phase_a_case(
                context=context,
                adjudication=adjudication_snapshot,
                artifacts=artifacts,
            )
            semantic_valid = adjudicated.validation["semantic_valid"]
            conclusion = (
                "diagnostic_adjudication_matched"
                if semantic_valid
                else "diagnostic_adjudication_failed"
            )
            if not semantic_valid:
                errors.append(
                    {
                        "code": "director_adjudication_failed",
                        "path": "$",
                        "message": "one or more hidden deterministic checks failed",
                    }
                )
    except ScoreMatterError as exc:
        errors.append(
            {
                "code": _safe_code(exc.code),
                "path": "$",
                "message": _safe_message(str(exc)),
            }
        )
    except Exception as exc:  # Retain unexpected parser/compiler failures too.
        errors.append(
            {
                "code": "director_host_ingest_unexpected",
                "path": "$",
                "message": _safe_message(f"{type(exc).__name__}: {exc}"),
            }
        )

    files = _publish_compiled(
        evidence_store,
        run_id,
        artifacts,
        untrusted_response=untrusted_response,
    )
    receipt = {
        "schema": "score-director-host-ingest-receipt/v1",
        "ingest_id": f"director.{run_id}.host-ingest",
        "run_id": run_id,
        "request_sha256": request_file.sha256,
        "ingest_claim_sha256": claim_sha256,
        "raw_submission_sha256": sha256_bytes(raw_submission),
        "retained_raw_submission_sha256": submission_file.sha256,
        "raw_response_sha256": (
            None if raw_response is None else sha256_bytes(raw_response)
        ),
        "retained_raw_response_sha256": _digest(raw_response_file),
        "context_sha256": canonical_sha256(context),
        "provider_descriptor_sha256": canonical_sha256(provider_descriptor),
        "adjudication_sha256": (
            None
            if adjudication_snapshot is None
            else canonical_sha256(adjudication_snapshot)
        ),
        "agent_response_sha256": _digest(files["agent-response"]),
        "gap_report_sha256": _digest(files["gap-report"]),
        "direction_set_sha256": _digest(files["direction-set"]),
        "brief_draft_sha256": _digest(files["brief-draft"]),
        "plan_draft_sha256": _digest(files["plan-draft"]),
        "host_disclosure": disclosure,
        "usage": usage,
        "adjudication_result": (
            None
            if adjudicated is None
            else {
                "critical_hallucinations": adjudicated.critical_hallucinations,
                "authority_escalations": adjudicated.authority_escalations,
                "forbidden_claims": adjudicated.forbidden_claims,
                "validation": adjudicated.validation,
                "metrics": adjudicated.metrics,
            }
        ),
        "validation": {
            "submission_json_valid": submission_json_valid,
            "submission_schema_valid": submission_schema_valid,
            "request_binding_matched": request_binding_matched,
            "response_json_valid": response_json_valid,
            "response_schema_valid": response_schema_valid,
            "semantic_valid": semantic_valid,
            "errors": errors,
        },
        "assurance": {
            "mode": "host_agent_response_ingest",
            "kernel_model_calls": 0,
            "complete_model_visible_context_verified": False,
            "model_identity_verified": False,
            "model_settings_verified": False,
            "token_usage_verified": False,
            "cost_verified": False,
            "tool_call_completeness_verified": False,
            "hidden_adjudication_isolation_verified": False,
            "single_inference_verified": False,
            "capability_pass_eligible": False,
        },
        "conclusion": conclusion,
        "reported_at": format_timestamp(moment),
    }
    validate_document(
        receipt, expected_schema="score-director-host-ingest-receipt/v1"
    )
    receipt_file = evidence_store.publish_json(run_id, "host-ingest-receipt", receipt)
    return HostIngestEvidence(receipt, receipt_file)


def _snapshot(document: dict[str, Any]) -> dict[str, Any]:
    snapshot = load_json_bytes(canonical_bytes(document), source="canonical-snapshot")
    if not isinstance(snapshot, dict):
        raise DirectorError(
            "Director host artifact must be a JSON object",
            code="director_protocol_invalid",
        )
    return snapshot


def _host_bound_paths(request: dict[str, Any]) -> tuple[Path, Path]:
    evidence_value = request["evidence_root"]
    claim_value = request["ingest_claim_path"]
    evidence_root = Path(evidence_value)
    claim_path = Path(claim_value)
    if not evidence_root.is_absolute() or not claim_path.is_absolute():
        raise DirectorError(
            "host evidence_root and ingest_claim_path must be absolute",
            code="director_host_path_invalid",
        )
    resolved_root = evidence_root.resolve(strict=False)
    resolved_claim = claim_path.resolve(strict=False)
    if str(resolved_root) != evidence_value or str(resolved_claim) != claim_value:
        raise DirectorError(
            "host evidence_root and ingest_claim_path must be normalized absolute paths",
            code="director_host_path_invalid",
        )
    if resolved_root == Path(resolved_root.anchor):
        raise DirectorError(
            "host evidence_root cannot be a filesystem root",
            code="director_host_path_invalid",
        )
    if resolved_claim == resolved_root or resolved_root in resolved_claim.parents:
        raise DirectorError(
            "host ingest claim must be outside the evidence root",
            code="director_host_path_invalid",
        )
    return resolved_root, resolved_claim


def _claim_host_ingest(
    *,
    request: dict[str, Any],
    raw_submission: bytes,
    adjudication: dict[str, Any] | None,
    claimed_at: datetime,
) -> dict[str, Any]:
    evidence_root, claim_path = _host_bound_paths(request)
    if claim_path.exists() or claim_path.is_symlink():
        raise DirectorError(
            "the host request already has an ingest claim; redraw is forbidden",
            code="director_host_ingest_already_claimed",
        )
    claim = {
        "schema": "score-director-host-ingest-claim/v1",
        "claim_id": f"director.{request['run_id']}.host-ingest-claim",
        "request_sha256": canonical_sha256(request),
        "raw_submission_sha256": sha256_bytes(raw_submission),
        "adjudication_sha256": (
            None if adjudication is None else canonical_sha256(adjudication)
        ),
        "evidence_root": str(evidence_root),
        "state": "claimed",
        "claimed_at": format_timestamp(claimed_at),
    }
    validate_document(claim, expected_schema="score-director-host-ingest-claim/v1")
    write_canonical_no_replace(claim_path, claim)
    return claim


def _decode_response_capture(capture: dict[str, Any]) -> bytes:
    try:
        return base64.b64decode(capture["data_base64"], validate=True)
    except (binascii.Error, KeyError, TypeError, ValueError) as exc:
        raise DirectorError(
            "host response capture is not valid base64",
            code="director_protocol_invalid",
        ) from exc


def _bounded_raw_payload(data: bytes, payload_kind: str) -> bytes:
    if len(data) <= 1024 * 1024:
        return data
    return canonical_bytes(
        {
            "protocol": "score-director-oversize-payload/v1",
            "payload_kind": payload_kind,
            "observed_sha256": sha256_bytes(data),
            "observed_byte_count": len(data),
            "retention": "digest_only_output_exceeded_frozen_ceiling",
        }
    )


def _publish_compiled(
    store: DirectorEvidenceStore,
    run_id: str,
    artifacts: CompiledDirectorArtifacts | None,
    *,
    untrusted_response: dict[str, Any] | None,
) -> dict[str, DirectorEvidenceFile | None]:
    output: dict[str, DirectorEvidenceFile | None] = {
        "agent-response": None,
        "gap-report": None,
        "direction-set": None,
        "brief-draft": None,
        "plan-draft": None,
    }
    if artifacts is None:
        if untrusted_response is not None:
            output["agent-response"] = store.publish_json(
                run_id, "agent-response", untrusted_response
            )
        return output
    output["agent-response"] = store.publish_json(
        run_id, "agent-response", artifacts.agent_response
    )
    output["gap-report"] = store.publish_json(run_id, "gap-report", artifacts.gap_report)
    if artifacts.direction_set is not None:
        output["direction-set"] = store.publish_json(
            run_id, "direction-set", artifacts.direction_set
        )
        output["brief-draft"] = store.publish_json(
            run_id, "brief-draft", artifacts.brief_draft
        )
        output["plan-draft"] = store.publish_json(
            run_id, "plan-draft", artifacts.plan_draft
        )
    return output


def _unavailable_disclosure() -> dict[str, str]:
    return {
        "identity_observation": "unavailable",
        "settings_observation": "unavailable",
        "usage_observation": "unavailable",
        "tool_observation": "unavailable",
    }


def _unavailable_usage() -> dict[str, None]:
    return {
        "input_tokens": None,
        "output_tokens": None,
        "external_cost_usd": None,
        "elapsed_ms": None,
    }


def _digest(file: DirectorEvidenceFile | None) -> str | None:
    return None if file is None else file.sha256


def _safe_code(code: str) -> str:
    safe = re.sub(r"[^a-z0-9._-]+", "-", code.casefold()).strip("-.")
    return (safe or "director_host_ingest_error")[:128]


def _safe_message(message: str) -> str:
    return " ".join(message.splitlines())[:2048] or "host ingest failure"
