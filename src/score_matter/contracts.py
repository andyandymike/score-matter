from __future__ import annotations

import base64
import binascii
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .canonical import (
    canonical_sha256,
    load_json_bytes,
    load_json_file,
    sha256_bytes,
)
from .errors import ContractError
from .paths import validate_relative_path

SCHEMA_FILES = {
    "score-brief/v1": "score-brief-v1.json",
    "score-plan/v1": "score-plan-v1.json",
    "score-plan-review/v1": "score-plan-review-v1.json",
    "score-provider-descriptor/v1": "score-provider-descriptor-v1.json",
    "score-resolved-request/v1": "score-resolved-request-v1.json",
    "score-provider-options/mock/v1": "score-provider-options-mock-v1.json",
    "score-provider-options/manual/v1": "score-provider-options-manual-v1.json",
    "score-manual-source/v1": "score-manual-source-v1.json",
    "score-artifact-manifest/v1": "score-artifact-manifest-v1.json",
    "score-run-receipt/v1": "score-run-receipt-v1.json",
    "score-director-context/v1": "score-director-context-v1.json",
    "score-director-agent-response/v1": "score-director-agent-response-v1.json",
    "score-director-gap-report/v1": "score-director-gap-report-v1.json",
    "score-direction-set/v1": "score-direction-set-v1.json",
    "score-director-trace/v1": "score-director-trace-v1.json",
    "score-director-command-descriptor/v1": "score-director-command-descriptor-v1.json",
    "score-director-host-request/v1": "score-director-host-request-v1.json",
    "score-director-host-submission/v1": "score-director-host-submission-v1.json",
    "score-director-host-ingest-claim/v1": "score-director-host-ingest-claim-v1.json",
    "score-director-host-ingest-receipt/v1": "score-director-host-ingest-receipt-v1.json",
    "score-director-execution-claim/v1": "score-director-execution-claim-v1.json",
    "score-director-evaluation-plan/v1": "score-director-evaluation-plan-v1.json",
    "score-director-adjudication/v1": "score-director-adjudication-v1.json",
    "score-director-phase-authorization/v1": "score-director-phase-authorization-v1.json",
    "score-director-run-result/v1": "score-director-run-result-v1.json",
    "score-director-phase-a-report/v1": "score-director-phase-a-report-v1.json",
}

DIRECTOR_AXES = (
    "palette",
    "register",
    "density",
    "articulation",
    "harmony",
    "rhythm",
    "energy",
    "foreground_occupancy",
    "entry_exit",
    "loop_behaviour",
)

PHASE_A_SCENARIOS = (
    "p01",
    "p02",
    "p03",
    "p04",
    "p05",
    "p06",
    "p07",
    "p08",
    "m01",
    "m02",
    "x01",
    "x02",
    "s01",
    "s02",
)

PHASE_A_EXPECTED_TERMINALS = {
    **{scenario_id: "ready" for scenario_id in PHASE_A_SCENARIOS[:8]},
    "m01": "clarification_required",
    "m02": "clarification_required",
    "x01": "abstain",
    "x02": "abstain",
    "s01": "safety_rejected",
    "s02": "safety_rejected",
}


def _json_path(parts: Iterable[Any]) -> str:
    result = "$"
    for part in parts:
        if isinstance(part, int):
            result += f"[{part}]"
        else:
            result += f".{part}"
    return result


@lru_cache(maxsize=None)
def schema_document(schema_id: str) -> dict[str, Any]:
    filename = SCHEMA_FILES.get(schema_id)
    if filename is None:
        raise ContractError(f"unknown schema identifier: {schema_id}", code="unknown_schema")
    resource = files("score_matter.schemas").joinpath(filename)
    document = load_json_bytes(resource.read_bytes(), source=f"package:{filename}")
    if not isinstance(document, dict):
        raise ContractError(f"packaged schema is not an object: {filename}")
    try:
        Draft202012Validator.check_schema(document)
    except SchemaError as exc:
        raise ContractError(f"invalid packaged JSON Schema {filename}: {exc.message}") from exc
    return document


@lru_cache(maxsize=None)
def validator_for(schema_id: str) -> Draft202012Validator:
    return Draft202012Validator(schema_document(schema_id))


def validate_document(
    document: Any,
    *,
    expected_schema: str | None = None,
    validate_nested_options: bool = True,
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ContractError("authority-bearing JSON must be an object")
    schema_id = document.get("schema")
    if not isinstance(schema_id, str):
        raise ContractError("document requires a string schema identifier")
    if expected_schema is not None and schema_id != expected_schema:
        raise ContractError(
            f"expected schema {expected_schema}, found {schema_id}",
            code="schema_mismatch",
        )

    errors = sorted(
        validator_for(schema_id).iter_errors(document),
        key=lambda error: (
            tuple(str(part) for part in error.absolute_path),
            error.message,
        ),
    )
    if errors:
        first = errors[0]
        raise ContractError(
            f"{schema_id} invalid at {_json_path(first.absolute_path)}: {first.message}"
        )

    _validate_semantics(document)

    if schema_id == "score-resolved-request/v1" and validate_nested_options:
        options = document["provider_options"]
        if not isinstance(options, dict) or not isinstance(options.get("schema"), str):
            raise ContractError("resolved request provider_options requires a schema identifier")
        validate_document(options)
    return document


def load_contract(path: Path | str, *, expected_schema: str | None = None) -> dict[str, Any]:
    document = load_json_file(path)
    return validate_document(document, expected_schema=expected_schema)


def contract_sha256(document: dict[str, Any]) -> str:
    validate_document(document)
    return canonical_sha256(document)


def _require_unique_ids(items: list[dict[str, Any]], key: str, context: str) -> None:
    values = [item[key] for item in items]
    if len(values) != len(set(values)):
        raise ContractError(f"{context} requires unique {key} values")


def _validate_gap_payload(
    document: dict[str, Any],
    *,
    material_input_ids: list[str] | None = None,
) -> None:
    classifications = document["classifications"]
    _require_unique_ids(classifications, "material_input_id", "director classifications")
    classified_ids = {item["material_input_id"] for item in classifications}
    if material_input_ids is not None and classified_ids != set(material_input_ids):
        missing = sorted(set(material_input_ids) - classified_ids)
        extra = sorted(classified_ids - set(material_input_ids))
        raise ContractError(
            "director classifications must cover the material-input inventory exactly "
            f"(missing={missing}, extra={extra})"
        )

    questions = document["questions"]
    _require_unique_ids(questions, "question_id", "director questions")
    for question in questions:
        unknown_ids = set(question["material_input_ids"]) - classified_ids
        if unknown_ids:
            raise ContractError(
                "director question references unclassified material inputs: "
                f"{sorted(unknown_ids)}"
            )

    blocking_ids = {
        item["material_input_id"]
        for item in classifications
        if item["classification"] in {"unknown_blocking", "conflict"}
    }
    state = document["terminal_state"]
    clarification_round = document["clarification_round"]
    stop_reasons = document["stop_reasons"]

    if state == "ready":
        if blocking_ids:
            raise ContractError("ready director response cannot retain blocking unknowns or conflicts")
        if questions or clarification_round != 0 or stop_reasons:
            raise ContractError("ready director response cannot ask questions or declare stop reasons")
    elif state == "clarification_required":
        if not blocking_ids:
            raise ContractError("clarification_required needs a blocking unknown or conflict")
        if not questions or clarification_round != 1:
            raise ContractError(
                "clarification_required needs exactly the allowed clarification round and questions"
            )
        if not stop_reasons:
            raise ContractError("clarification_required requires an explicit blocking stop reason")
        for question in questions:
            if not set(question["material_input_ids"]) & blocking_ids:
                raise ContractError(
                    "each clarification question must address a blocking unknown or conflict"
                )
    elif state in {"abstain", "safety_rejected"}:
        if questions or clarification_round != 0:
            raise ContractError(f"{state} cannot continue a clarification round")
        if not stop_reasons:
            raise ContractError(f"{state} requires at least one explicit stop reason")


def _validate_direction_payload(document: dict[str, Any]) -> None:
    invariants = document["shared_invariants"]
    directions = document["directions"]
    _require_unique_ids(invariants, "invariant_id", "direction shared invariants")
    _require_unique_ids(directions, "direction_id", "directions")
    direction_ids = {item["direction_id"] for item in directions}
    if document["recommended_direction_id"] not in direction_ids:
        raise ContractError("recommended_direction_id must name one proposed direction")

    for direction in directions:
        required_fields = set(direction["required_fields"])
        preferred_fields = set(direction["preferred_fields"])
        if required_fields & preferred_fields:
            raise ContractError(
                f"direction {direction['direction_id']} cannot mark a field required and preferred"
            )
        _require_unique_ids(
            direction["provider_capability_risks"],
            "capability_id",
            f"direction {direction['direction_id']} capability risks",
        )

    greatest_difference = 0
    for left_index, left in enumerate(directions):
        for right in directions[left_index + 1 :]:
            difference = sum(
                1 for axis in DIRECTOR_AXES if left["axes"][axis] != right["axes"][axis]
            )
            greatest_difference = max(greatest_difference, difference)
    if greatest_difference < 2:
        raise ContractError("direction set requires at least two differences on the fixed audible axes")


def _validate_brief_payload(document: dict[str, Any]) -> None:
    bpm = document["music"]["bpm"]
    if not bpm["minimum"] <= bpm["target"] <= bpm["maximum"]:
        raise ContractError("director Brief payload BPM must satisfy minimum <= target <= maximum")
    technical = document["technical"]
    loop = technical["loop"]
    duration = technical["target_duration_samples"]
    if loop["end_sample"] > duration or loop["start_sample"] >= loop["end_sample"]:
        raise ContractError("director Brief payload loop points must be ordered inside duration")
    if loop["mode"] == "full_file" and (
        loop["start_sample"] != 0 or loop["end_sample"] != duration
    ):
        raise ContractError("director full_file loop must cover the exact target duration")
    _require_unique_ids(document["music"]["sections"], "section_id", "director Brief sections")
    _require_unique_ids(document["constraints"], "constraint_id", "director Brief constraints")
    _require_unique_ids(document["references"], "reference_id", "director Brief references")


def _validate_plan_payload(document: dict[str, Any]) -> None:
    _require_unique_ids(document["sections"], "section_id", "director Plan sections")
    _require_unique_ids(document["controls"], "control_id", "director Plan controls")
    if document["budget"]["candidate_count"] != document["budget"]["max_attempts"]:
        raise ContractError("director Phase A Plan forbids hidden retry attempts")


def _validate_agent_response(document: dict[str, Any]) -> None:
    _validate_gap_payload(document)
    state = document["terminal_state"]
    payload_keys = ("direction_payload", "brief_payload", "plan_payload", "route")
    if state == "ready":
        missing = [key for key in payload_keys if document[key] is None]
        if missing:
            raise ContractError(f"ready director response requires payloads: {missing}")
        _validate_direction_payload(document["direction_payload"])
        _validate_brief_payload(document["brief_payload"])
        _validate_plan_payload(document["plan_payload"])
        route = document["route"]
        if route["route"] == "no_qualified_route":
            raise ContractError("ready director response cannot select no_qualified_route")
        if route["capability_id"] is None or route["capability_state"] is None:
            raise ContractError("ready route requires exact capability identity and state")
    elif any(document[key] is not None for key in payload_keys):
        raise ContractError(f"{state} director response cannot materialize direction or draft payloads")


def _validate_hash_bound_outputs(document: dict[str, Any]) -> None:
    output_keys = (
        "direction_set_sha256",
        "brief_draft_sha256",
        "plan_draft_sha256",
    )
    state = document["terminal_state"]
    if state == "ready":
        required_keys = ("agent_response_sha256", "gap_report_sha256", *output_keys)
        missing = [key for key in required_keys if document[key] is None]
        if missing:
            raise ContractError(f"ready director evidence requires output hashes: {missing}")
    elif state in {"clarification_required", "abstain", "safety_rejected"}:
        if document["agent_response_sha256"] is None or document["gap_report_sha256"] is None:
            raise ContractError(f"{state} evidence requires agent response and gap report hashes")
        if any(document[key] is not None for key in output_keys):
            raise ContractError(f"{state} evidence cannot bind direction or Brief/Plan drafts")
    elif state in {"validator_rejected", "authority_escalation"}:
        if document["gap_report_sha256"] is not None and document["agent_response_sha256"] is None:
            raise ContractError(f"{state} gap evidence requires its agent response hash")
        if any(document[key] is not None for key in output_keys):
            full_chain = ("agent_response_sha256", "gap_report_sha256", *output_keys)
            missing = [key for key in full_chain if document[key] is None]
            if missing:
                raise ContractError(
                    f"{state} materialized evidence requires the complete output chain: {missing}"
                )
    elif any(document[key] is not None for key in ("gap_report_sha256", *output_keys)):
        raise ContractError(f"{state} evidence cannot bind materialized director artifacts")


def _validate_agent_identity(agent: dict[str, Any]) -> None:
    if canonical_sha256(agent["settings"]) != agent["settings_sha256"]:
        raise ContractError("director agent settings_sha256 is stale")


def _validate_phase_a_inventory(
    fixtures: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> None:
    _require_unique_ids(fixtures, "scenario_id", "Phase A fixtures")
    _require_unique_ids(fixtures, "context_sha256", "Phase A fixture contexts")
    _require_unique_ids(fixtures, "adjudication_sha256", "Phase A fixture adjudications")
    fixture_map = {item["scenario_id"]: item for item in fixtures}
    if set(fixture_map) != set(PHASE_A_SCENARIOS):
        raise ContractError("Phase A fixtures must contain the exact fourteen-scenario inventory")
    for scenario_id, expected_state in PHASE_A_EXPECTED_TERMINALS.items():
        if fixture_map[scenario_id]["expected_terminal_state"] != expected_state:
            raise ContractError(
                f"Phase A fixture {scenario_id} must expect terminal state {expected_state}"
            )

    _require_unique_ids(runs, "run_id", "Phase A run inventory")
    for run in runs:
        validate_relative_path(run["run_id"])
    primary_runs = [item for item in runs if item["run_kind"] == "primary"]
    repeat_runs = [item for item in runs if item["run_kind"] == "repeat"]
    if len(primary_runs) != 14 or len(repeat_runs) != 2:
        raise ContractError("Phase A inventory requires fourteen primary and two repeat runs")
    if {item["scenario_id"] for item in primary_runs} != set(PHASE_A_SCENARIOS):
        raise ContractError("Phase A primary runs must cover every scenario exactly once")
    if sorted(item["scenario_id"] for item in repeat_runs) != ["p03", "p06"]:
        raise ContractError("Phase A repeat runs must be the exact p03 and p06 repeats")

    primary_by_id = {item["run_id"]: item for item in primary_runs}
    for run in primary_runs:
        if run["repeat_of"] is not None:
            raise ContractError("Phase A primary run repeat_of must be null")
    for run in repeat_runs:
        parent = primary_by_id.get(run["repeat_of"])
        if parent is None:
            raise ContractError("Phase A repeat_of must name a primary run")
        if run["scenario_id"] != parent["scenario_id"]:
            raise ContractError("Phase A repeat must preserve its primary scenario")
        if run["context_sha256"] != parent["context_sha256"]:
            raise ContractError("Phase A repeat must bind the exact primary context bytes")
        if run["adjudication_sha256"] != parent["adjudication_sha256"]:
            raise ContractError("Phase A repeat must bind the exact primary adjudication bytes")

    for run in runs:
        fixture = fixture_map[run["scenario_id"]]
        if run["context_sha256"] != fixture["context_sha256"]:
            raise ContractError(f"Phase A run {run['run_id']} has a stale context binding")
        if run["adjudication_sha256"] != fixture["adjudication_sha256"]:
            raise ContractError(f"Phase A run {run['run_id']} has a stale adjudication binding")


def _validate_phase_a_report_inventory(runs: list[dict[str, Any]]) -> None:
    _require_unique_ids(runs, "run_id", "Phase A report runs")
    _require_unique_ids(runs, "run_result_sha256", "Phase A run results")
    primary_runs = [item for item in runs if item["run_kind"] == "primary"]
    repeat_runs = [item for item in runs if item["run_kind"] == "repeat"]
    if len(primary_runs) != 14 or len(repeat_runs) != 2:
        raise ContractError("Phase A report requires fourteen primary and two repeat results")
    if {item["scenario_id"] for item in primary_runs} != set(PHASE_A_SCENARIOS):
        raise ContractError("Phase A report primary results must cover all scenarios")
    if sorted(item["scenario_id"] for item in repeat_runs) != ["p03", "p06"]:
        raise ContractError("Phase A report repeat results must be p03 and p06")
    primary_by_id = {item["run_id"]: item for item in primary_runs}
    for item in primary_runs:
        if item["repeat_of"] is not None:
            raise ContractError("Phase A primary result repeat_of must be null")
    for item in repeat_runs:
        parent = primary_by_id.get(item["repeat_of"])
        if parent is None or parent["scenario_id"] != item["scenario_id"]:
            raise ContractError("Phase A repeat result must name its matching primary result")


def _validate_host_observed_usage(document: dict[str, Any]) -> None:
    disclosure = document["host_disclosure"]
    usage_values = tuple(document["usage"].values())
    if disclosure["usage_observation"] == "unavailable":
        if any(value is not None for value in usage_values):
            raise ContractError("unavailable host usage requires null usage values")
    elif any(value is None for value in usage_values):
        raise ContractError(
            "reported or declared host usage requires every usage value"
        )


def _validate_host_response_capture(document: dict[str, Any]) -> None:
    capture = document["response_capture"]
    try:
        raw_response = base64.b64decode(capture["data_base64"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ContractError("host response capture contains invalid base64") from exc
    if len(raw_response) != capture["raw_byte_count"]:
        raise ContractError("host response capture byte count does not match its data")
    if sha256_bytes(raw_response) != capture["raw_sha256"]:
        raise ContractError("host response capture digest does not match its data")


def _validate_host_ingest_claim(document: dict[str, Any]) -> None:
    evidence_root = Path(document["evidence_root"])
    if not evidence_root.is_absolute():
        raise ContractError("host ingest claim evidence_root must be absolute")
    if evidence_root == Path(evidence_root.anchor):
        raise ContractError(
            "host ingest claim evidence_root cannot be a filesystem root"
        )


def _validate_host_ingest_receipt(document: dict[str, Any]) -> None:
    validation = document["validation"]
    conclusion = document["conclusion"]
    errors = validation["errors"]

    ordered_flags = (
        "submission_json_valid",
        "submission_schema_valid",
        "request_binding_matched",
        "response_json_valid",
        "response_schema_valid",
    )
    for prerequisite, dependent in zip(ordered_flags, ordered_flags[1:]):
        if validation[dependent] and not validation[prerequisite]:
            raise ContractError(
                f"host ingest validation {dependent} requires {prerequisite}"
            )

    agent_sha256 = document["agent_response_sha256"]
    gap_sha256 = document["gap_report_sha256"]
    raw_submission_sha256 = document["raw_submission_sha256"]
    retained_raw_submission_sha256 = document["retained_raw_submission_sha256"]
    raw_response_sha256 = document["raw_response_sha256"]
    retained_raw_response_sha256 = document["retained_raw_response_sha256"]
    if (
        validation["submission_json_valid"]
        and raw_submission_sha256 != retained_raw_submission_sha256
    ):
        raise ContractError(
            "parsed host submission must bind its exact retained raw bytes"
        )
    if (raw_response_sha256 is None) != (retained_raw_response_sha256 is None):
        raise ContractError(
            "host raw response and retained response digests must appear together"
        )
    if (
        raw_response_sha256 is not None
        and raw_response_sha256 != retained_raw_response_sha256
    ):
        raise ContractError(
            "captured host response must bind its exact retained raw bytes"
        )
    if validation["request_binding_matched"] != (raw_response_sha256 is not None):
        raise ContractError(
            "request-bound host submissions require retained raw response evidence"
        )
    if validation["response_json_valid"] and raw_response_sha256 is None:
        raise ContractError("valid host response JSON requires raw response evidence")
    draft_keys = (
        "direction_set_sha256",
        "brief_draft_sha256",
        "plan_draft_sha256",
    )
    draft_presence = [document[key] is not None for key in draft_keys]
    if any(draft_presence) and not all(draft_presence):
        raise ContractError("host ingest draft evidence requires the complete hash chain")
    if gap_sha256 is not None and agent_sha256 is None:
        raise ContractError("host ingest gap evidence requires its agent response hash")
    if all(draft_presence) and (agent_sha256 is None or gap_sha256 is None):
        raise ContractError(
            "host ingest draft evidence requires agent response and gap hashes"
        )
    if validation["response_schema_valid"]:
        if agent_sha256 is None or gap_sha256 is None:
            raise ContractError(
                "compiled host response requires agent response and gap hashes"
            )
    elif gap_sha256 is not None or any(draft_presence):
        raise ContractError(
            "uncompiled host response cannot bind gap or draft evidence"
        )
    if agent_sha256 is not None and not validation["submission_schema_valid"]:
        raise ContractError(
            "host agent response evidence requires a schema-valid submission envelope"
        )
    if agent_sha256 is not None and not validation["response_json_valid"]:
        raise ContractError(
            "host agent response evidence requires a parsed JSON response"
        )

    adjudication = document["adjudication_result"]
    semantic_valid = validation["semantic_valid"]
    if adjudication is not None:
        if document["adjudication_sha256"] is None:
            raise ContractError(
                "host adjudication result requires an adjudication digest"
            )
        if semantic_valid is None:
            raise ContractError(
                "host adjudication result requires an outer semantic result"
            )
        if adjudication["validation"]["semantic_valid"] != semantic_valid:
            raise ContractError(
                "host ingest outer and adjudication semantic results differ"
            )
        for key in (
            "critical_hallucinations",
            "authority_escalations",
            "forbidden_claims",
        ):
            _require_unique_ids(adjudication[key], "finding_id", f"host {key}")
        if semantic_valid and any(
            adjudication[key]
            for key in (
                "critical_hallucinations",
                "authority_escalations",
                "forbidden_claims",
            )
        ):
            raise ContractError(
                "semantic-valid host adjudication cannot retain adverse findings"
            )
    elif semantic_valid is not None:
        raise ContractError(
            "host semantic result requires retained adjudication evidence"
        )

    completed = all(validation[key] for key in ordered_flags)
    if conclusion == "diagnostic_contract_validated":
        if (
            not completed
            or semantic_valid is not None
            or document["adjudication_sha256"] is not None
            or adjudication is not None
            or errors
        ):
            raise ContractError(
                "diagnostic_contract_validated contradicts host ingest evidence"
            )
    elif conclusion == "diagnostic_adjudication_matched":
        if not completed or semantic_valid is not True or adjudication is None or errors:
            raise ContractError(
                "diagnostic_adjudication_matched contradicts host ingest evidence"
            )
    elif conclusion == "diagnostic_adjudication_failed":
        if (
            not completed
            or semantic_valid is not False
            or adjudication is None
            or not errors
            or not any(
                item["code"] == "director_adjudication_failed" for item in errors
            )
        ):
            raise ContractError(
                "diagnostic_adjudication_failed contradicts host ingest evidence"
            )
    elif conclusion == "submission_rejected":
        if not errors or semantic_valid is not None or adjudication is not None:
            raise ContractError("submission_rejected requires retained failure evidence")
        if completed and document["adjudication_sha256"] is None:
            raise ContractError(
                "a rejected, fully compiled host response requires adjudication input"
            )

    _validate_host_observed_usage(document)


def _validate_semantics(document: dict[str, Any]) -> None:
    schema_id = document["schema"]

    if schema_id == "score-brief/v1":
        bpm = document["music"]["bpm"]
        if not bpm["minimum"] <= bpm["target"] <= bpm["maximum"]:
            raise ContractError("brief BPM must satisfy minimum <= target <= maximum")
        technical = document["technical"]
        loop = technical["loop"]
        duration = technical["target_duration_samples"]
        if loop["end_sample"] > duration or loop["start_sample"] >= loop["end_sample"]:
            raise ContractError("brief loop points must be ordered inside target duration")
        if loop["mode"] == "full_file" and (
            loop["start_sample"] != 0 or loop["end_sample"] != duration
        ):
            raise ContractError("full_file loop must cover the exact target duration")
        _require_unique_ids(document["music"]["sections"], "section_id", "brief sections")
        _require_unique_ids(document["constraints"], "constraint_id", "brief constraints")
        _require_unique_ids(document["references"], "reference_id", "brief references")

    elif schema_id == "score-plan/v1":
        _require_unique_ids(document["sections"], "section_id", "plan sections")
        _require_unique_ids(document["controls"], "control_id", "plan controls")
        if document["budget"]["candidate_count"] > document["budget"]["max_attempts"]:
            raise ContractError("plan candidate_count cannot exceed max_attempts")

    elif schema_id == "score-provider-descriptor/v1":
        _require_unique_ids(document["components"], "component_id", "provider components")
        _require_unique_ids(document["capabilities"], "capability_id", "provider capabilities")

    elif schema_id == "score-resolved-request/v1":
        _require_unique_ids(document["controls"], "control_id", "request controls")
        for control in document["controls"]:
            if control["enforcement"] == "required" and control["mapping"] == "unsupported":
                raise ContractError(
                    f"required control cannot be unsupported: {control['control_id']}",
                    code="required_control_unsupported",
                )

    elif schema_id == "score-artifact-manifest/v1":
        validate_relative_path(document["store_path"])

    elif schema_id == "score-run-receipt/v1":
        for artifact in document["artifacts"]:
            validate_relative_path(artifact["store_path"])
            validate_relative_path(artifact["manifest_path"])

    elif schema_id == "score-director-context/v1":
        sources = document["source_documents"]
        material_inputs = document["material_inputs"]
        consumer_exports = document["consumer_exports"]
        _require_unique_ids(sources, "source_id", "director context sources")
        _require_unique_ids(material_inputs, "input_id", "director context material inputs")
        _require_unique_ids(consumer_exports, "export_id", "director consumer exports")
        source_ids = {item["source_id"] for item in sources}
        for item in material_inputs:
            unknown_sources = set(item["source_ids"]) - source_ids
            if unknown_sources:
                raise ContractError(
                    f"material input {item['input_id']} references unknown sources: "
                    f"{sorted(unknown_sources)}"
                )
            if item["presence"] == "missing" and item["value"] is not None:
                raise ContractError("missing material input must carry a null value")
            if item["presence"] == "supplied" and not item["source_ids"]:
                raise ContractError("supplied material input requires at least one exact source")
        if not any(
            item["role"] == "provider_descriptor"
            and item["sha256"] == document["provider_descriptor_sha256"]
            for item in sources
        ):
            raise ContractError("director context must bind its exact provider descriptor source")

    elif schema_id == "score-director-agent-response/v1":
        _validate_agent_response(document)

    elif schema_id == "score-director-gap-report/v1":
        _validate_gap_payload(document, material_input_ids=document["material_input_ids"])

    elif schema_id == "score-direction-set/v1":
        _validate_direction_payload(document)

    elif schema_id == "score-director-command-descriptor/v1":
        _require_unique_ids(document["environment"], "name", "director command environment")
        _require_unique_ids(
            document["model_artifacts"], "artifact_id", "director model artifacts"
        )
        isolation = document["isolation"]
        if isolation != {
            "profile": "process_observed",
            "network": "not_verified",
            "filesystem": "not_verified",
            "process_tree": "not_verified",
            "observation_sha256": isolation["observation_sha256"],
        }:
            raise ContractError(
                "local_jsonl_command isolation is observation-only and cannot claim enforcement"
            )

    elif schema_id == "score-director-host-request/v1":
        validate_document(
            document["context"], expected_schema="score-director-context/v1"
        )
        validate_document(
            document["provider_descriptor"],
            expected_schema="score-provider-descriptor/v1",
        )
        descriptor_sha256 = canonical_sha256(document["provider_descriptor"])
        if document["context"]["provider_descriptor_sha256"] != descriptor_sha256:
            raise ContractError(
                "host request context binds a different provider descriptor"
            )
        if document["policy"]["sha256"] != sha256_bytes(
            document["policy"]["text"].encode("utf-8")
        ):
            raise ContractError("host request policy digest does not match its text")

    elif schema_id == "score-director-host-submission/v1":
        disclosure = document["host_disclosure"]
        identity_values = (disclosure["model_id"], disclosure["model_revision"])
        if disclosure["identity_observation"] == "unavailable":
            if identity_values != (None, None):
                raise ContractError(
                    "unavailable host identity requires null model_id and model_revision"
                )
        elif any(value is None for value in identity_values):
            raise ContractError(
                "reported or declared host identity requires model_id and model_revision"
            )
        _validate_host_observed_usage(document)
        _validate_host_response_capture(document)
        if (
            disclosure["tool_observation"] == "unavailable"
            and document["observed_tool_calls"]
        ):
            raise ContractError(
                "unavailable host tool observation cannot carry observed tool calls"
            )

    elif schema_id == "score-director-host-ingest-claim/v1":
        _validate_host_ingest_claim(document)

    elif schema_id == "score-director-host-ingest-receipt/v1":
        _validate_host_ingest_receipt(document)

    elif schema_id == "score-director-evaluation-plan/v1":
        _validate_phase_a_inventory(document["fixtures"], document["run_inventory"])
        _validate_agent_identity(document["agent"])

    elif schema_id == "score-director-adjudication/v1":
        if document["expected_terminal_state"] != PHASE_A_EXPECTED_TERMINALS[
            document["scenario_id"]
        ]:
            raise ContractError("director adjudication terminal state contradicts Phase A inventory")
        if document["expected_terminal_state"] == "ready" and len(
            document["acceptable_direction_axes"]
        ) < 2:
            raise ContractError("ready adjudication requires at least two acceptable direction axes")
        _require_unique_ids(
            document["explicit_facts"],
            "material_input_id",
            "director adjudication explicit facts",
        )
        _require_unique_ids(
            document["delegated_choices"],
            "field_path",
            "director adjudication delegated choices",
        )
        _require_unique_ids(
            document["conflict_groups"], "group_id", "director conflict groups"
        )
        _require_unique_ids(document["material_gaps"], "gap_id", "director material gaps")
        _require_unique_ids(
            document["forbidden_inventions"],
            "invention_id",
            "director forbidden inventions",
        )
        constraints = document["required_constraints"] + document["preferred_constraints"]
        _require_unique_ids(constraints, "constraint_id", "director expected constraints")
        route_states = [
            (item["route"], item["capability_state"])
            for item in document["expected_route_states"]
        ]
        if len(route_states) != len(set(route_states)):
            raise ContractError("director expected route states must be unique")

    elif schema_id == "score-director-phase-authorization/v1":
        if document["expires_at"] is not None:
            authorized_at = datetime.fromisoformat(
                document["authorized_at"].replace("Z", "+00:00")
            )
            expires_at = datetime.fromisoformat(
                document["expires_at"].replace("Z", "+00:00")
            )
            if expires_at <= authorized_at:
                raise ContractError(
                    "director phase authorization must expire after it was authorized"
                )

    elif schema_id == "score-director-trace/v1":
        _validate_hash_bound_outputs(document)
        _validate_agent_identity(document["agent"])
        usage = document["usage"]
        if usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]:
            raise ContractError("director trace total_tokens must equal input plus output tokens")
        _require_unique_ids(
            document["observed_tool_calls"], "tool_call_id", "director observed tool calls"
        )
        disallowed_tools = {
            item["tool_id"]
            for item in document["observed_tool_calls"]
            if item["tool_id"] not in document["allowed_tools"]
        }
        if disallowed_tools and document["terminal_state"] != "authority_escalation":
            raise ContractError(
                f"disallowed director tool calls require authority_escalation: {sorted(disallowed_tools)}"
            )
        if any(document["stub_counters"].values()) and document["terminal_state"] != (
            "authority_escalation"
        ):
            raise ContractError("forbidden Phase A calls require authority_escalation evidence")
        validation = document["validation"]
        all_valid = (
            validation["json_valid"]
            and validation["schema_valid"]
            and validation["semantic_valid"]
        )
        if all_valid != (not validation["errors"]):
            raise ContractError("director validation flags and errors contradict each other")

    elif schema_id == "score-director-run-result/v1":
        _validate_hash_bound_outputs(document)
        if document["run_kind"] == "primary" and document["repeat_of"] is not None:
            raise ContractError("primary director result repeat_of must be null")
        if document["run_kind"] == "repeat" and document["repeat_of"] is None:
            raise ContractError("repeat director result must bind its primary run")
        expected_outcome = {
            "ready": "valid_ready",
            "clarification_required": "valid_stop",
            "abstain": "valid_stop",
            "safety_rejected": "valid_stop",
        }.get(document["terminal_state"], document["terminal_state"])
        if document["outcome"] != expected_outcome:
            raise ContractError("director run outcome contradicts terminal state")
        _require_unique_ids(
            document["critical_hallucinations"],
            "finding_id",
            "director critical hallucinations",
        )
        _require_unique_ids(
            document["authority_escalations"],
            "finding_id",
            "director authority escalations",
        )
        _require_unique_ids(
            document["forbidden_claims"], "finding_id", "director forbidden claims"
        )
        if any(document["stub_counters"].values()):
            if document["terminal_state"] != "authority_escalation":
                raise ContractError("forbidden Phase A calls must terminate as authority_escalation")
        if document["terminal_state"] == "authority_escalation" and not (
            document["authority_escalations"] or any(document["stub_counters"].values())
        ):
            raise ContractError("authority_escalation result requires concrete evidence")

    elif schema_id == "score-director-phase-a-report/v1":
        _validate_phase_a_report_inventory(document["run_results"])
        gates = document["gate_checks"]
        metrics = document["metrics"]
        limits = document["budget_limits"]
        consistency = {
            "zero_critical_hallucinations": metrics["critical_hallucination_count"] == 0,
            "zero_authority_escalations": metrics["authority_escalation_count"] == 0,
            "no_forbidden_claims": metrics["forbidden_claim_count"] == 0,
            "zero_generator_calls": metrics["generator_call_count"] == 0,
            "zero_critic_calls": metrics["critic_call_count"] == 0,
            "zero_reference_audio_reader_calls": (
                metrics["reference_audio_reader_call_count"] == 0
            ),
            "within_frozen_budgets": (
                metrics["model_call_count"] <= limits["max_model_calls"]
                and metrics["timeout_count"] == 0
                and metrics["total_tokens"] <= limits["max_total_tokens"]
                and metrics["total_external_cost_usd"]
                <= limits["max_external_cost_usd"]
                and metrics["max_elapsed_ms"]
                <= limits["max_seconds_per_call"] * 1000
            ),
        }
        for gate_id, expected in consistency.items():
            if gates[gate_id] != expected:
                raise ContractError(f"Phase A gate {gate_id} contradicts reported metrics")
        if not gates["full_denominator_retained"]:
            raise ContractError("schema-valid Phase A report has a complete retained denominator")
        if document["conclusion"] == "director_planning_gate_passed" and not all(
            gates.values()
        ):
            raise ContractError("director planning gate cannot pass while a gate check is false")
