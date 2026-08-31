from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from score_matter.canonical import canonical_sha256
from score_matter.contracts import validate_document
from score_matter.errors import DirectorError

from .compiler import CompiledDirectorArtifacts
from .semantic import AXIS_NAMES, contains_frozen_phrase


@dataclass(frozen=True)
class AdjudicationResult:
    critical_hallucinations: list[dict[str, str]]
    authority_escalations: list[dict[str, str]]
    forbidden_claims: list[dict[str, str]]
    validation: dict[str, bool | None]
    metrics: dict[str, int | float | bool | None]


def adjudicate_phase_a_case(
    *,
    context: dict[str, Any],
    adjudication: dict[str, Any],
    artifacts: CompiledDirectorArtifacts,
) -> AdjudicationResult:
    """Apply only hash-bound, deterministic Phase A checks.

    This is not a second model and does not judge whether music is aesthetically
    good.  The hidden sheet can check explicit provenance, stop behavior,
    target projection, route state, and named-axis diversity.
    """

    validate_document(context, expected_schema="score-director-context/v1")
    validate_document(
        adjudication, expected_schema="score-director-adjudication/v1"
    )
    context_sha256 = canonical_sha256(context)
    if adjudication["context_sha256"] != context_sha256:
        raise DirectorError(
            "hidden adjudication binds a different context",
            code="director_adjudication_mismatch",
        )
    if adjudication["spec_sha256"] != context["spec_sha256"]:
        raise DirectorError(
            "hidden adjudication and context bind different specifications",
            code="director_adjudication_mismatch",
        )
    if adjudication["scenario_id"] != context["scenario_id"]:
        raise DirectorError(
            "hidden adjudication and context scenario differ",
            code="director_adjudication_mismatch",
        )

    response = artifacts.agent_response
    terminal_matches = (
        response["terminal_state"] == adjudication["expected_terminal_state"]
    )
    critical: list[dict[str, str]] = []
    forbidden: list[dict[str, str]] = []
    classifications = {
        item["material_input_id"]: item["classification"]
        for item in response["classifications"]
    }
    context_inputs = {item["input_id"]: item for item in context["material_inputs"]}
    inputs_by_path: dict[str, list[dict[str, Any]]] = {}
    for item in context["material_inputs"]:
        inputs_by_path.setdefault(item["field_path"], []).append(item)

    for fact in adjudication["explicit_facts"]:
        input_id = fact["material_input_id"]
        source = context_inputs.get(input_id)
        if source is None or source["field_path"] != fact["field_path"]:
            raise DirectorError(
                f"hidden explicit fact is stale: {input_id}",
                code="director_adjudication_mismatch",
            )
        if source["value"] != fact["expected_value"]:
            raise DirectorError(
                f"hidden explicit fact value is stale: {input_id}",
                code="director_adjudication_mismatch",
            )
        if classifications.get(input_id) != fact["expected_classification"]:
            critical.append(
                _finding(
                    f"fact-classification-{len(critical) + 1}",
                    input_id,
                    "explicit source material was reclassified",
                )
            )
        if artifacts.brief_draft is not None:
            present, value = _get_path(artifacts.brief_draft, fact["field_path"])
            if not present or value != fact["expected_value"]:
                critical.append(
                    _finding(
                        f"fact-projection-{len(critical) + 1}",
                        fact["field_path"],
                        "Brief draft did not preserve the exact explicit fact",
                    )
                )

    expected_gap_ids: set[str] = set()
    for gap in adjudication["material_gaps"]:
        candidates = inputs_by_path.get(gap["field_path"], [])
        if len(candidates) != 1:
            raise DirectorError(
                f"hidden gap does not select one context input: {gap['field_path']}",
                code="director_adjudication_mismatch",
            )
        input_id = candidates[0]["input_id"]
        expected_gap_ids.add(input_id)
        if classifications.get(input_id) != gap["expected_classification"]:
            critical.append(
                _finding(
                    f"gap-classification-{len(critical) + 1}",
                    gap["field_path"],
                    "material gap or conflict was not classified as frozen",
                )
            )

    for group in adjudication["conflict_groups"]:
        for input_id in group["material_input_ids"]:
            if input_id not in context_inputs:
                raise DirectorError(
                    f"hidden conflict names an absent input: {input_id}",
                    code="director_adjudication_mismatch",
                )
            if classifications.get(input_id) != "conflict":
                critical.append(
                    _finding(
                        f"conflict-{len(critical) + 1}",
                        input_id,
                        "one member of a frozen hard conflict was not retained",
                    )
                )

    for expected_classification, key in (
        ("required_constraint", "required_constraints"),
        ("preferred_constraint", "preferred_constraints"),
    ):
        for expected in adjudication[key]:
            input_id = expected["material_input_id"]
            source = context_inputs.get(input_id)
            if (
                source is None
                or source["field_path"] != expected["field_path"]
                or source["value"] != expected["expected_value"]
            ):
                raise DirectorError(
                    f"hidden constraint is stale: {input_id}",
                    code="director_adjudication_mismatch",
                )
            if classifications.get(input_id) != expected_classification:
                critical.append(
                    _finding(
                        f"constraint-classification-{len(critical) + 1}",
                        input_id,
                        f"constraint was not classified as {expected_classification}",
                    )
                )

    for choice in adjudication["delegated_choices"]:
        candidates = inputs_by_path.get(choice["field_path"], [])
        if len(candidates) != 1:
            raise DirectorError(
                f"delegated choice does not select one context input: {choice['field_path']}",
                code="director_adjudication_mismatch",
            )
        input_id = candidates[0]["input_id"]
        if classifications.get(input_id) != "assumption_proposed_for_review":
            critical.append(
                _finding(
                    f"delegated-choice-{len(critical) + 1}",
                    choice["field_path"],
                    "creative choice was presented without assumption provenance",
                )
            )
        if artifacts.brief_draft is not None:
            present, value = _get_path(artifacts.brief_draft, choice["field_path"])
            if not present or not _choice_allowed(choice, value):
                critical.append(
                    _finding(
                        f"delegated-value-{len(critical) + 1}",
                        choice["field_path"],
                        "delegated creative value is absent or outside its frozen envelope",
                    )
                )

    constraints_preserved: bool | None = None
    route_matched: bool | None = None
    direction_diverse: bool | None = None
    direction_difference_count: int | None = None
    if artifacts.brief_draft is not None and artifacts.plan_draft is not None:
        constraint_findings = _constraint_findings(adjudication, artifacts)
        critical.extend(constraint_findings)
        constraints_preserved = not constraint_findings

        direction = artifacts.direction_set
        assert direction is not None
        recommended = next(
            item
            for item in direction["directions"]
            if item["direction_id"] == direction["recommended_direction_id"]
        )
        for target in adjudication["required_positive_targets"]:
            if target not in recommended["emotional_targets"]:
                critical.append(
                    _finding(
                        f"positive-target-{len(critical) + 1}",
                        target,
                        "required positive target is absent from the recommended direction",
                    )
                )
        for target in adjudication["required_anti_targets"]:
            if target not in recommended["anti_targets"]:
                critical.append(
                    _finding(
                        f"anti-target-{len(critical) + 1}",
                        target,
                        "required anti-target is absent from the recommended direction",
                    )
                )
        direction_difference_count = _maximum_allowed_axis_difference(
            direction["directions"], adjudication["acceptable_direction_axes"]
        )
        direction_diverse = direction_difference_count >= 2
        if not direction_diverse:
            critical.append(
                _finding(
                    f"direction-diversity-{len(critical) + 1}",
                    str(direction_difference_count),
                    "no direction pair differs on two hidden-accepted audible axes",
                )
            )
        route_matched = any(
            expected["route"] == artifacts.route["route"]
            and expected["capability_state"] == artifacts.route["capability_state"]
            for expected in adjudication["expected_route_states"]
        )
        if not route_matched:
            critical.append(
                _finding(
                    f"route-{len(critical) + 1}",
                    str(artifacts.route),
                    "route or capability state differs from hidden frozen expectations",
                )
            )
        if (
            artifacts.plan_draft["profiles"]["evaluation_profile_id"]
            != adjudication["expected_critic_profile_id"]
        ):
            critical.append(
                _finding(
                    f"critic-profile-{len(critical) + 1}",
                    artifacts.plan_draft["profiles"]["evaluation_profile_id"],
                    "Phase A critic policy differs from the hidden frozen profile",
                )
            )

    flattened = "\n".join(_strings(response)).casefold()
    for phrase in adjudication["forbidden_authority_claims"]:
        if contains_frozen_phrase(flattened, phrase):
            forbidden.append(
                _finding(
                    f"forbidden-claim-{len(forbidden) + 1}",
                    phrase,
                    "agent-controlled text contains a frozen forbidden authority claim",
                )
            )
    for invention in adjudication["forbidden_inventions"]:
        if contains_frozen_phrase(flattened, invention["statement"]):
            critical.append(
                _finding(
                    f"forbidden-invention-{len(critical) + 1}",
                    invention["statement"],
                    "agent output states a pre-registered forbidden invention",
                )
            )

    predicted_gap_ids = {
        item["material_input_id"]
        for item in response["classifications"]
        if item["classification"] in {"unknown_blocking", "unknown_non_blocking", "conflict"}
    }
    missing_recall = _ratio(len(expected_gap_ids & predicted_gap_ids), len(expected_gap_ids))
    missing_precision = _ratio(len(expected_gap_ids & predicted_gap_ids), len(predicted_gap_ids))
    brief_plan_complete = artifacts.brief_draft is not None and artifacts.plan_draft is not None
    semantic_valid = terminal_matches and not critical and not forbidden
    return AdjudicationResult(
        critical_hallucinations=critical,
        authority_escalations=[],
        forbidden_claims=forbidden,
        validation={
            "context_hash_matched": True,
            "schema_valid": True,
            "semantic_valid": semantic_valid,
            "expected_stop_matched": terminal_matches,
            "required_constraints_preserved": constraints_preserved,
            "route_state_matched": route_matched,
            "direction_diversity_verified": direction_diverse,
        },
        metrics={
            "missing_field_recall": missing_recall,
            "missing_field_precision": missing_precision,
            "direction_axis_difference_count": direction_difference_count,
            "brief_plan_complete": brief_plan_complete,
            "route_correct": route_matched,
            "stop_correct": terminal_matches,
        },
    )


def _constraint_findings(
    adjudication: dict[str, Any], artifacts: CompiledDirectorArtifacts
) -> list[dict[str, str]]:
    assert artifacts.brief_draft is not None
    assert artifacts.plan_draft is not None
    brief = {item["constraint_id"]: item for item in artifacts.brief_draft["constraints"]}
    plan = {item["control_id"]: item for item in artifacts.plan_draft["controls"]}
    findings: list[dict[str, str]] = []
    for enforcement, key in (
        ("required", "required_constraints"),
        ("preferred", "preferred_constraints"),
    ):
        for expected in adjudication[key]:
            identifier = expected["constraint_id"]
            expected_record = {
                "enforcement": enforcement,
                "value": expected["expected_value"],
            }
            brief_record = brief.get(identifier)
            plan_record = plan.get(identifier)
            if brief_record is None or {
                "enforcement": brief_record["enforcement"],
                "value": brief_record["value"],
            } != expected_record:
                findings.append(
                    _finding(
                        f"brief-constraint-{len(findings) + 1}",
                        identifier,
                        "Brief draft lost or changed a frozen constraint",
                    )
                )
            if plan_record is None or {
                "enforcement": plan_record["enforcement"],
                "value": plan_record["value"],
            } != expected_record:
                findings.append(
                    _finding(
                        f"plan-control-{len(findings) + 1}",
                        identifier,
                        "Plan draft lost or changed a frozen constraint",
                    )
                )
    return findings


def _choice_allowed(choice: dict[str, Any], value: Any) -> bool:
    if "allowed_values" in choice:
        return value in choice["allowed_values"]
    kind = choice["allowed_kind"]
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "string":
        return isinstance(value, str) and bool(value)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    return False


def _get_path(document: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = document
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return False, None
        current = current[part]
    return True, current


def _maximum_allowed_axis_difference(
    directions: Sequence[Mapping[str, Any]], allowed_axes: Sequence[str]
) -> int:
    maximum = 0
    for left_index, left in enumerate(directions):
        for right in directions[left_index + 1 :]:
            count = sum(
                _normalized(left["axes"][axis]) != _normalized(right["axes"][axis])
                for axis in allowed_axes
                if axis in AXIS_NAMES
            )
            maximum = max(maximum, count)
    return maximum


def _normalized(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return repr(value)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        output: list[str] = []
        for item in value.values():
            output.extend(_strings(item))
        return output
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        output = []
        for item in value:
            output.extend(_strings(item))
        return output
    return []


def _ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _finding(finding_id: str, evidence: str, rationale: str) -> dict[str, str]:
    return {"finding_id": finding_id, "evidence": evidence, "rationale": rationale}
