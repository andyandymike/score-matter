from __future__ import annotations

import copy
import unittest
from typing import Any

from score_matter.canonical import canonical_sha256
from score_matter.director.adjudicator import adjudicate_phase_a_case
from score_matter.director.compiler import compile_agent_response
from score_matter.errors import DirectorError

from tests.test_director_contracts import (
    _adjudication,
    _agent_response_ready,
    _context,
    _digest,
)


def _provider_descriptor() -> dict[str, Any]:
    return {
        "schema": "score-provider-descriptor/v1",
        "provider_id": "phase-a-fixture-provider",
        "adapter_version": "0.1.0",
        "execution_mode": "local",
        "protocol_version": "score-provider-protocol/v1",
        "components": [
            {
                "component_id": "fixture-generator",
                "kind": "generator",
                "locator": "fixture://no-audio-execution",
                "revision": "fixture-1",
                "sha256": _digest(700),
                "license_snapshot_id": "fixture-license",
            }
        ],
        "capabilities": [
            {
                "capability_id": "text_to_music",
                "state": "experimental",
                "constraints": {"phase_a_execution": False},
                "evidence": "fixture descriptor used only for route validation",
            }
        ],
        "limits": {
            "max_input_bytes": 1048576,
            "max_duration_samples": 230400000,
            "formats": ["wav_pcm_s16le"],
        },
    }


def _ready_context(
    descriptor: dict[str, Any] | None = None,
    *,
    scenario_id: str = "p01",
    spec_sha256: str | None = None,
) -> dict[str, Any]:
    provider = descriptor or _provider_descriptor()
    provider_sha256 = canonical_sha256(provider)
    context = _context()
    context.update(
        {
            "context_id": f"context-{scenario_id}",
            "scenario_id": scenario_id,
            "cue_id": f"cue-{scenario_id}",
            "spec_sha256": spec_sha256 or _digest(1),
            "provider_descriptor_sha256": provider_sha256,
        }
    )
    for source in context["source_documents"]:
        if source["role"] == "provider_descriptor":
            source["sha256"] = provider_sha256
    context["material_inputs"].append(
        {
            "input_id": "anti-trailer",
            "field_path": "constraints.anti_trailer",
            "presence": "supplied",
            "value": True,
            "source_ids": ["human"],
        }
    )
    return context


def _ready_response(context: dict[str, Any]) -> dict[str, Any]:
    response = _agent_response_ready()
    response["context_sha256"] = canonical_sha256(context)
    response["classifications"].append(
        {
            "material_input_id": "anti-trailer",
            "classification": "required_constraint",
            "statement": "Trailer bombast is explicitly forbidden.",
            "rationale": "The human-authored context marks this anti-target required.",
        }
    )
    return response


def _ready_adjudication(context: dict[str, Any]) -> dict[str, Any]:
    adjudication = _adjudication()
    adjudication.update(
        {
            "adjudication_id": f"adjudication-{context['scenario_id']}",
            "spec_sha256": context["spec_sha256"],
            "context_sha256": canonical_sha256(context),
            "scenario_id": context["scenario_id"],
            "expected_terminal_state": "ready",
            "delegated_choices": [],
            "material_gaps": [],
            "conflict_groups": [],
            "forbidden_inventions": [],
            "required_positive_targets": ["wonder"],
            "required_anti_targets": ["trailer bombast"],
            "expected_critic_profile_id": "score-director.critic-disabled.phase-a",
        }
    )
    adjudication["explicit_facts"] = [
        {
            "material_input_id": "role",
            "field_path": "gameplay.role",
            "expected_classification": "explicit_fact",
            "expected_value": "exploration",
        }
    ]
    adjudication["required_constraints"] = [
        {
            "constraint_id": "anti_target.trailer",
            "material_input_id": "anti-trailer",
            "field_path": "constraints.anti_trailer",
            "expected_value": True,
            "statement": "Trailer shorthand remains forbidden.",
        }
    ]
    adjudication["preferred_constraints"] = []
    adjudication["acceptable_direction_axes"] = ["palette", "rhythm"]
    adjudication["expected_route_states"] = [
        {"route": "text_to_music", "capability_state": "experimental"}
    ]
    return adjudication


def _stopped_context(
    terminal_state: str,
    descriptor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = _ready_context(descriptor)
    context["material_inputs"] = [
        {
            "input_id": "role",
            "field_path": "gameplay.role",
            "presence": "missing" if terminal_state == "clarification_required" else "supplied",
            "value": None if terminal_state == "clarification_required" else "conflicting-role",
            "source_ids": [] if terminal_state == "clarification_required" else ["human"],
        }
    ]
    return context


def _stopped_response(
    context: dict[str, Any],
    terminal_state: str,
) -> dict[str, Any]:
    classification = "unknown_blocking" if terminal_state == "clarification_required" else "conflict"
    questions = []
    clarification_round = 0
    if terminal_state == "clarification_required":
        questions = [
            {
                "question_id": "question-role",
                "material_input_ids": ["role"],
                "text": "What gameplay role must this cue serve?",
                "why_material": "The role changes foreground occupancy and structure.",
            }
        ]
        clarification_round = 1
    return {
        "schema": "score-director-agent-response/v1",
        "context_sha256": canonical_sha256(context),
        "terminal_state": terminal_state,
        "classifications": [
            {
                "material_input_id": "role",
                "classification": classification,
                "statement": "The gameplay role is unresolved.",
                "rationale": "The supplied context cannot support a resolved Brief.",
            }
        ],
        "questions": questions,
        "clarification_round": clarification_round,
        "stop_reasons": ["A material gameplay requirement remains unresolved."],
        "direction_payload": None,
        "brief_payload": None,
        "plan_payload": None,
        "route": None,
    }


class DirectorCompilerTests(unittest.TestCase):
    def test_ready_response_materializes_all_drafts_and_gap(self) -> None:
        descriptor = _provider_descriptor()
        context = _ready_context(descriptor)
        response = _ready_response(context)

        artifacts = compile_agent_response(
            run_id="run-p01",
            context=context,
            provider_descriptor=descriptor,
            response=response,
        )

        self.assertEqual(artifacts.gap_report["terminal_state"], "ready")
        self.assertEqual(
            set(artifacts.gap_report["material_input_ids"]),
            {"role", "anti-trailer"},
        )
        self.assertIsNotNone(artifacts.direction_set)
        self.assertIsNotNone(artifacts.brief_draft)
        self.assertIsNotNone(artifacts.plan_draft)
        self.assertEqual(artifacts.route["route"], "text_to_music")
        self.assertEqual(
            artifacts.plan_draft["brief_sha256"],
            canonical_sha256(artifacts.brief_draft),
        )

    def test_clarification_and_abstain_materialize_no_downstream_drafts(self) -> None:
        descriptor = _provider_descriptor()
        for terminal_state in ("clarification_required", "abstain"):
            with self.subTest(terminal_state=terminal_state):
                context = _stopped_context(terminal_state, descriptor)
                response = _stopped_response(context, terminal_state)
                artifacts = compile_agent_response(
                    run_id=f"run-{terminal_state}",
                    context=context,
                    provider_descriptor=descriptor,
                    response=response,
                )
                self.assertEqual(artifacts.gap_report["terminal_state"], terminal_state)
                self.assertIsNone(artifacts.direction_set)
                self.assertIsNone(artifacts.brief_draft)
                self.assertIsNone(artifacts.plan_draft)
                self.assertIsNone(artifacts.route)

    def test_anti_target_is_projected_into_brief_and_plan_with_same_id(self) -> None:
        descriptor = _provider_descriptor()
        context = _ready_context(descriptor)
        artifacts = compile_agent_response(
            run_id="run-p01",
            context=context,
            provider_descriptor=descriptor,
            response=_ready_response(context),
        )
        brief_controls = {
            item["constraint_id"]: item for item in artifacts.brief_draft["constraints"]
        }
        plan_controls = {
            item["control_id"]: item for item in artifacts.plan_draft["controls"]
        }
        projected_ids = {
            identifier
            for identifier, item in brief_controls.items()
            if item["value"] == "trailer bombast" and item["enforcement"] == "required"
        }
        self.assertEqual(len(projected_ids), 1)
        projected_id = projected_ids.pop()
        self.assertEqual(plan_controls[projected_id]["value"], "trailer bombast")
        self.assertEqual(plan_controls[projected_id]["enforcement"], "required")

    def test_authority_claim_is_rejected_before_materialization(self) -> None:
        descriptor = _provider_descriptor()
        context = _ready_context(descriptor)
        response = _ready_response(context)
        response["direction_payload"]["recommendation_basis"] = (
            "This direction is approved and release-ready."
        )
        with self.assertRaises(DirectorError) as raised:
            compile_agent_response(
                run_id="run-p01",
                context=context,
                provider_descriptor=descriptor,
                response=response,
            )
        self.assertEqual(raised.exception.code, "director_authority_escalation")

    def test_route_capability_identity_and_state_must_match_descriptor(self) -> None:
        descriptor = _provider_descriptor()
        context = _ready_context(descriptor)

        response = _ready_response(context)
        response["route"]["route"] = "audio_to_audio"
        with self.assertRaises(DirectorError) as wrong_route:
            compile_agent_response(
                run_id="run-p01",
                context=context,
                provider_descriptor=descriptor,
                response=response,
            )
        self.assertEqual(wrong_route.exception.code, "director_route_invalid")

        response = _ready_response(context)
        response["route"]["capability_id"] = "absent-capability"
        with self.assertRaises(DirectorError) as missing:
            compile_agent_response(
                run_id="run-p01",
                context=context,
                provider_descriptor=descriptor,
                response=response,
            )
        self.assertEqual(missing.exception.code, "director_route_invalid")

        response = _ready_response(context)
        response["route"]["capability_state"] = "verified"
        with self.assertRaises(DirectorError) as escalated:
            compile_agent_response(
                run_id="run-p01",
                context=context,
                provider_descriptor=descriptor,
                response=response,
            )
        self.assertEqual(escalated.exception.code, "director_capability_escalation")

    def test_hidden_adjudication_accepts_exact_projection_and_detects_drift(self) -> None:
        descriptor = _provider_descriptor()
        context = _ready_context(descriptor)
        adjudication = _ready_adjudication(context)
        artifacts = compile_agent_response(
            run_id="run-p01",
            context=context,
            provider_descriptor=descriptor,
            response=_ready_response(context),
        )
        result = adjudicate_phase_a_case(
            context=context,
            adjudication=adjudication,
            artifacts=artifacts,
        )
        self.assertTrue(result.validation["semantic_valid"])
        self.assertTrue(result.validation["required_constraints_preserved"])
        self.assertTrue(result.validation["route_state_matched"])
        self.assertTrue(result.validation["direction_diversity_verified"])
        self.assertEqual(result.critical_hallucinations, [])

        drifted = _ready_response(context)
        drifted["brief_payload"]["gameplay"]["role"] = "combat"
        drifted_artifacts = compile_agent_response(
            run_id="run-p01-drifted",
            context=context,
            provider_descriptor=descriptor,
            response=drifted,
        )
        drifted_result = adjudicate_phase_a_case(
            context=context,
            adjudication=adjudication,
            artifacts=drifted_artifacts,
        )
        self.assertFalse(drifted_result.validation["semantic_valid"])
        self.assertTrue(
            any(
                finding["finding_id"].startswith("fact-projection-")
                for finding in drifted_result.critical_hallucinations
            )
        )


if __name__ == "__main__":
    unittest.main()
