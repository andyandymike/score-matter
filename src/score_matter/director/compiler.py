from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from score_matter.canonical import canonical_sha256
from score_matter.contracts import validate_document
from score_matter.errors import DirectorError

from .semantic import has_material_direction_pair, reject_authority_escalation

_TERMINAL_WITH_DRAFTS = "ready"
_CRITIC_PROFILE = "score-director.critic-disabled.phase-a"
_CRITIC_CONTROL = {
    "control_id": "critic_policy",
    "value": "disabled_phase_a",
    "enforcement": "required",
}


@dataclass(frozen=True)
class CompiledDirectorArtifacts:
    agent_response: dict[str, Any]
    gap_report: dict[str, Any]
    direction_set: dict[str, Any] | None
    brief_draft: dict[str, Any] | None
    plan_draft: dict[str, Any] | None
    route: dict[str, Any] | None


def compile_agent_response(
    *,
    run_id: str,
    context: dict[str, Any],
    provider_descriptor: dict[str, Any],
    response: dict[str, Any],
) -> CompiledDirectorArtifacts:
    """Validate untrusted semantic payload and add deterministic envelopes.

    No mood, orchestration, harmony, tempo, or structural choice is made here.
    The compiler only binds identities, projects explicit anti/positive targets,
    applies experiment invariants, and rejects stale or unsupported claims.
    """

    validate_document(context, expected_schema="score-director-context/v1")
    validate_document(
        provider_descriptor, expected_schema="score-provider-descriptor/v1"
    )
    validate_document(response, expected_schema="score-director-agent-response/v1")
    reject_authority_escalation(response)

    context_sha256 = canonical_sha256(context)
    if response["context_sha256"] != context_sha256:
        raise DirectorError(
            "agent response binds a different director context",
            code="director_context_mismatch",
        )
    _validate_classification_coverage(context, response)
    _validate_terminal_payloads(response)
    response_sha256 = canonical_sha256(response)

    gap = {
        "schema": "score-director-gap-report/v1",
        "gap_report_id": _artifact_id(context["scenario_id"], "gap", response_sha256),
        "context_sha256": context_sha256,
        "agent_response_sha256": response_sha256,
        "terminal_state": response["terminal_state"],
        "material_input_ids": sorted(
            item["input_id"] for item in context["material_inputs"]
        ),
        "classifications": response["classifications"],
        "questions": response["questions"],
        "clarification_round": response["clarification_round"],
        "stop_reasons": response["stop_reasons"],
    }
    validate_document(gap, expected_schema="score-director-gap-report/v1")

    if response["terminal_state"] != _TERMINAL_WITH_DRAFTS:
        return CompiledDirectorArtifacts(response, gap, None, None, None, None)

    direction_payload = response["direction_payload"]
    assert isinstance(direction_payload, dict)
    gap_sha256 = canonical_sha256(gap)
    direction_set = {
        "schema": "score-direction-set/v1",
        "direction_set_id": _artifact_id(
            context["scenario_id"], "directions", response_sha256
        ),
        "context_sha256": context_sha256,
        "agent_response_sha256": response_sha256,
        "gap_report_sha256": gap_sha256,
        **direction_payload,
    }
    validate_document(direction_set, expected_schema="score-direction-set/v1")
    if not has_material_direction_pair(direction_set["directions"]):
        raise DirectorError(
            "direction set lacks a pair differing on at least two frozen axes",
            code="director_directions_not_distinct",
        )

    recommended = next(
        direction
        for direction in direction_set["directions"]
        if direction["direction_id"] == direction_set["recommended_direction_id"]
    )
    target_controls = _target_controls(recommended)

    brief_payload = response["brief_payload"]
    plan_payload = response["plan_payload"]
    route = response["route"]
    assert isinstance(brief_payload, dict)
    assert isinstance(plan_payload, dict)
    assert isinstance(route, dict)

    brief = {
        "schema": "score-brief/v1",
        "brief_id": _artifact_id(context["scenario_id"], "brief", response_sha256),
        "revision": 1,
        "project_id": context["project_id"],
        "cue_id": context["cue_id"],
        "intended_use": context["intended_use"],
        **brief_payload,
    }
    brief["constraints"] = _merge_controls(
        brief["constraints"], target_controls, context="Brief constraints"
    )
    validate_document(brief, expected_schema="score-brief/v1")

    if plan_payload["profiles"]["evaluation_profile_id"] != _CRITIC_PROFILE:
        raise DirectorError(
            f"Phase A Plan must use evaluation_profile_id={_CRITIC_PROFILE}",
            code="director_critic_policy_mismatch",
        )
    plan_controls = [*target_controls, _CRITIC_CONTROL]
    plan = {
        "schema": "score-plan/v1",
        "plan_id": _artifact_id(context["scenario_id"], "plan", response_sha256),
        "brief_sha256": canonical_sha256(brief),
        "package_class": "evaluation_only",
        **plan_payload,
    }
    plan["controls"] = _merge_controls(
        plan["controls"], plan_controls, context="Plan controls"
    )
    validate_document(plan, expected_schema="score-plan/v1")
    if plan["sections"] != brief["music"]["sections"]:
        raise DirectorError(
            "Phase A Plan sections must exactly match the Brief draft sections",
            code="director_projection_mismatch",
        )
    if plan["budget"]["candidate_count"] != plan["budget"]["max_attempts"]:
        raise DirectorError(
            "Phase A draft forbids hidden rescue attempts",
            code="director_retry_budget_forbidden",
        )
    _validate_route(route, provider_descriptor)
    return CompiledDirectorArtifacts(response, gap, direction_set, brief, plan, route)


def _validate_classification_coverage(
    context: dict[str, Any], response: dict[str, Any]
) -> None:
    expected = sorted(item["input_id"] for item in context["material_inputs"])
    actual = sorted(item["material_input_id"] for item in response["classifications"])
    if actual != expected:
        raise DirectorError(
            "agent classifications must cover every material input exactly once",
            code="director_classification_coverage",
        )
    source_ids = {item["source_id"] for item in context["source_documents"]}
    for item in context["material_inputs"]:
        if not set(item["source_ids"]).issubset(source_ids):
            raise DirectorError(
                f"material input references an unknown source: {item['input_id']}",
                code="director_source_binding_invalid",
            )


def _validate_terminal_payloads(response: dict[str, Any]) -> None:
    terminal = response["terminal_state"]
    payloads = (
        response["direction_payload"],
        response["brief_payload"],
        response["plan_payload"],
        response["route"],
    )
    if terminal == "ready":
        if any(payload is None for payload in payloads):
            raise DirectorError(
                "ready agent response requires direction, Brief, Plan, and route payloads",
                code="director_terminal_payload_mismatch",
            )
        if response["questions"] or response["clarification_round"] != 0:
            raise DirectorError(
                "ready agent response cannot retain a clarification question",
                code="director_terminal_payload_mismatch",
            )
        blocking = {"unknown_blocking", "conflict"}
        if any(
            item["classification"] in blocking
            for item in response["classifications"]
        ):
            raise DirectorError(
                "ready agent response cannot contain a blocking unknown or conflict",
                code="director_terminal_payload_mismatch",
            )
        return
    if any(payload is not None for payload in payloads):
        raise DirectorError(
            f"{terminal} agent response cannot materialize planning payloads",
            code="director_terminal_payload_mismatch",
        )
    if terminal == "clarification_required":
        if not response["questions"] or response["clarification_round"] != 1:
            raise DirectorError(
                "clarification_required needs one round with one to three questions",
                code="director_terminal_payload_mismatch",
            )
    elif response["questions"] or response["clarification_round"] != 0:
        raise DirectorError(
            f"{terminal} cannot contain clarification questions",
            code="director_terminal_payload_mismatch",
        )
    if not response["stop_reasons"]:
        raise DirectorError(
            f"{terminal} requires an explicit stop reason",
            code="director_terminal_payload_mismatch",
        )


def _target_controls(direction: dict[str, Any]) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []
    for target in direction["emotional_targets"]:
        controls.append(
            {
                "constraint_id": f"target.{_text_token(target)}",
                "control_id": f"target.{_text_token(target)}",
                "enforcement": "preferred",
                "value": target,
            }
        )
    for target in direction["anti_targets"]:
        controls.append(
            {
                "constraint_id": f"anti_target.{_text_token(target)}",
                "control_id": f"anti_target.{_text_token(target)}",
                "enforcement": "required",
                "value": target,
            }
        )
    return controls


def _merge_controls(
    existing: list[dict[str, Any]],
    projected: list[dict[str, Any]],
    *,
    context: str,
) -> list[dict[str, Any]]:
    output = [dict(item) for item in existing]
    uses_constraint_id = context.startswith("Brief")
    key = "constraint_id" if uses_constraint_id else "control_id"
    by_id = {item[key]: item for item in output}
    for source in projected:
        item = {
            key: source[key],
            "enforcement": source["enforcement"],
            "value": source["value"],
        }
        previous = by_id.get(item[key])
        if previous is not None and previous != item:
            raise DirectorError(
                f"{context} conflicts with deterministic projection: {item[key]}",
                code="director_projection_mismatch",
            )
        if previous is None:
            output.append(item)
            by_id[item[key]] = item
    return output


def _validate_route(route: dict[str, Any], descriptor: dict[str, Any]) -> None:
    if route["route"] == "no_qualified_route":
        if route["capability_id"] is not None or route["capability_state"] is not None:
            raise DirectorError(
                "no_qualified_route cannot claim a capability",
                code="director_route_invalid",
            )
        return
    capability_id = route["capability_id"]
    expected_capability = {
        "text_to_music": "text_to_music",
        "audio_to_audio": "audio_to_audio",
        "inpainting": "inpainting",
        "continuation": "continuation",
        "manual_ingest": "manual_ingest",
        "replay_ingest": "artifact_replay",
        "deterministic_postprocess": "deterministic_postprocess",
    }[route["route"]]
    if capability_id != expected_capability:
        raise DirectorError(
            "director route and capability identifier do not correspond",
            code="director_route_invalid",
        )
    matches = [
        item for item in descriptor["capabilities"] if item["capability_id"] == capability_id
    ]
    if len(matches) != 1:
        raise DirectorError(
            "director route names an absent provider capability",
            code="director_route_invalid",
        )
    capability = matches[0]
    if route["capability_state"] != capability["state"]:
        raise DirectorError(
            "director route capability state differs from the frozen descriptor",
            code="director_capability_escalation",
        )
    if capability["state"] == "unsupported":
        raise DirectorError(
            "director selected an unsupported capability",
            code="director_route_invalid",
        )


def _artifact_id(scenario_id: str, kind: str, digest: str) -> str:
    safe_scenario = scenario_id[:48]
    return f"director.{safe_scenario}.{kind}.{digest.removeprefix('sha256:')[:16]}"


def _text_token(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
