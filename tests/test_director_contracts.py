from __future__ import annotations

import copy
import unittest
from pathlib import Path
from typing import Any

from score_matter.canonical import canonical_sha256
from score_matter.contracts import PHASE_A_EXPECTED_TERMINALS, PHASE_A_SCENARIOS, validate_document
from score_matter.director.kernel import director_kernel_sha256
from score_matter.errors import ContractError


_CONTRACT_EVIDENCE_ROOT = str(
    (Path.cwd() / ".local" / "contract-fixture-evidence").resolve()
)
_CONTRACT_CLAIM_PATH = str(
    (Path.cwd() / ".local-claims" / "contract-fixture-phase-a.json").resolve()
)


def _digest(index: int) -> str:
    return f"sha256:{index:064x}"


def _settings() -> dict[str, Any]:
    return {
        "temperature": 0.2,
        "top_p": 0.9,
        "max_output_tokens": 4096,
        "seed": 7,
        "response_format": "json",
    }


def _classification(
    input_id: str = "role",
    classification: str = "explicit_fact",
) -> dict[str, Any]:
    return {
        "material_input_id": input_id,
        "classification": classification,
        "statement": "The role is supplied by the context author.",
        "rationale": "This value is present in an exact human-authored source.",
    }


def _question(input_id: str = "role") -> dict[str, Any]:
    return {
        "question_id": f"question-{input_id}",
        "material_input_ids": [input_id],
        "text": "What gameplay role must the cue serve?",
        "why_material": "The answer changes foreground occupancy and structure.",
    }


def _axes(*, alternate: bool = False) -> dict[str, Any]:
    return {
        "palette": "muted strings" if not alternate else "soft glass and synth",
        "register": "middle",
        "density": "sparse",
        "articulation": "sustained",
        "harmony": "stable modal harmony",
        "rhythm": "slow pulse" if not alternate else "free floating rhythm",
        "energy": "low rising gently",
        "foreground_occupancy": "low",
        "entry_exit": "soft entry and resolved exit",
        "loop_behaviour": "low contrast full-file loop",
    }


def _direction(direction_id: str, *, alternate: bool = False) -> dict[str, Any]:
    return {
        "direction_id": direction_id,
        "title": "Quiet orbit" if not alternate else "Glass horizon",
        "gameplay_hypothesis": "A restrained bed preserves attention for exploration.",
        "emotional_targets": ["wonder"],
        "anti_targets": ["trailer bombast"],
        "axes": _axes(alternate=alternate),
        "dialogue_sfx_occupancy": "low",
        "neighbour_cue_behaviour": "Leaves headroom for the adjacent alert cue.",
        "expected_audible_evidence": ["The middle register remains sparse."],
        "likely_failure_modes": ["The pulse may become too foregrounded."],
        "required_fields": ["gameplay.role"],
        "preferred_fields": ["music.mood"],
        "provider_capability_risks": [
            {
                "capability_id": "text_to_music",
                "risk": "Fine structural adherence is experimental.",
                "required": True,
            }
        ],
        "difference_summary": "This direction changes palette and rhythm.",
    }


def _direction_payload() -> dict[str, Any]:
    return {
        "shared_invariants": [
            {
                "invariant_id": "dialogue_room",
                "statement": "Keep foreground occupancy low.",
                "enforcement": "required",
            }
        ],
        "directions": [_direction("quiet-orbit"), _direction("glass-horizon", alternate=True)],
        "recommended_direction_id": "quiet-orbit",
        "recommendation_authority": "agent_recommendation_for_fixture",
        "recommendation_basis": "The restrained pulse best supports navigation.",
    }


def _brief_payload() -> dict[str, Any]:
    return {
        "gameplay": {
            "role": "exploration",
            "foreground_occupancy": "low",
            "entry_intent": "fade in without announcing a new scene",
            "exit_intent": "resolve before the alert cue",
            "neighbor_cue_ids": ["alert"],
        },
        "music": {
            "instrumental": True,
            "mood": ["wonder"],
            "energy_curve": "low-rise",
            "bpm": {"minimum": 70, "target": 80, "maximum": 90},
            "key_mode": {"key": "d", "mode": "dorian"},
            "meter": {"beats": 4, "unit": 4},
            "sections": [
                {"section_id": "main", "bars": 8, "intent": "restrained exploration bed"}
            ],
            "instrumentation_prefer": ["muted-strings"],
            "instrumentation_avoid": ["brass-stabs"],
        },
        "technical": {
            "sample_rate_hz": 44100,
            "channels": 2,
            "target_duration_samples": 882000,
            "loop": {"mode": "none", "start_sample": 0, "end_sample": 882000},
            "source_format": "wav_pcm_s16le",
            "delivery_format": "wav_pcm_s16le",
            "loudness_profile_id": "game-bgm-eval",
        },
        "constraints": [
            {"constraint_id": "anti_target.trailer", "enforcement": "required", "value": True}
        ],
        "references": [],
    }


def _plan_payload() -> dict[str, Any]:
    return {
        "sections": [
            {"section_id": "main", "bars": 8, "intent": "restrained exploration bed"}
        ],
        "controls": [
            {"control_id": "anti_target.trailer", "value": True, "enforcement": "required"}
        ],
        "budget": {"candidate_count": 1, "max_attempts": 1, "max_runtime_seconds": 600},
        "profiles": {
            "qa_profile_id": "phase-a-no-audio",
            "evaluation_profile_id": "score-director.critic-disabled.phase-a",
        },
        "allowed_postprocess": [],
    }


def _agent_response_ready() -> dict[str, Any]:
    return {
        "schema": "score-director-agent-response/v1",
        "context_sha256": _digest(10),
        "terminal_state": "ready",
        "classifications": [_classification()],
        "questions": [],
        "clarification_round": 0,
        "stop_reasons": [],
        "direction_payload": _direction_payload(),
        "brief_payload": _brief_payload(),
        "plan_payload": _plan_payload(),
        "route": {
            "route": "text_to_music",
            "capability_id": "text_to_music",
            "capability_state": "experimental",
            "rationale": "The frozen descriptor exposes an experimental route.",
            "risks": ["Exact structure is not verified."],
        },
    }


def _context() -> dict[str, Any]:
    return {
        "schema": "score-director-context/v1",
        "context_id": "context-p01",
        "spec_sha256": _digest(1),
        "scenario_id": "p01",
        "project_id": "fixture-project",
        "cue_id": "cue-p01",
        "intended_use": "internal_eval",
        "provider_descriptor_sha256": _digest(3),
        "source_documents": [
            {"source_id": "human", "sha256": _digest(2), "role": "human_request"},
            {
                "source_id": "provider",
                "sha256": _digest(3),
                "role": "provider_descriptor",
            },
        ],
        "natural_language_request": "Create a restrained exploration bed.",
        "material_inputs": [
            {
                "input_id": "role",
                "field_path": "gameplay.role",
                "presence": "supplied",
                "value": "exploration",
                "source_ids": ["human"],
            }
        ],
        "consumer_exports": [],
    }


def _gap_report() -> dict[str, Any]:
    return {
        "schema": "score-director-gap-report/v1",
        "gap_report_id": "gap-p01",
        "context_sha256": _digest(10),
        "agent_response_sha256": _digest(11),
        "terminal_state": "ready",
        "material_input_ids": ["role"],
        "classifications": [_classification()],
        "questions": [],
        "clarification_round": 0,
        "stop_reasons": [],
    }


def _direction_set() -> dict[str, Any]:
    return {
        "schema": "score-direction-set/v1",
        "direction_set_id": "directions-p01",
        "context_sha256": _digest(10),
        "agent_response_sha256": _digest(11),
        "gap_report_sha256": _digest(12),
        **_direction_payload(),
    }


def _command_descriptor() -> dict[str, Any]:
    return {
        "schema": "score-director-command-descriptor/v1",
        "backend_id": "local_jsonl_command",
        "protocol_version": "score-director-jsonl/v1",
        "executable": "C:\\tools\\director.exe",
        "executable_sha256": _digest(20),
        "arguments": ["--offline", "--jsonl"],
        "environment": [{"name": "DIRECTOR_OFFLINE", "value": "1"}],
        "working_directory": "C:\\work\\score-director",
        "working_directory_manifest_sha256": _digest(23),
        "model_id": "local-director",
        "model_revision": "fixture-1",
        "model_artifacts": [
            {
                "artifact_id": "weights",
                "locator": "models/director.gguf",
                "revision": "fixture-1",
                "sha256": _digest(21),
                "license_snapshot_id": "license-fixture",
            }
        ],
        "max_output_bytes": 1048576,
        "isolation": {
            "profile": "process_observed",
            "network": "not_verified",
            "filesystem": "not_verified",
            "process_tree": "not_verified",
            "observation_sha256": _digest(22),
        },
    }


def _evaluation_plan() -> dict[str, Any]:
    fixtures = []
    fixture_by_scenario: dict[str, dict[str, Any]] = {}
    for index, scenario_id in enumerate(PHASE_A_SCENARIOS, start=100):
        fixture = {
            "scenario_id": scenario_id,
            "context_sha256": _digest(index),
            "adjudication_sha256": _digest(index + 100),
            "expected_terminal_state": PHASE_A_EXPECTED_TERMINALS[scenario_id],
        }
        fixtures.append(fixture)
        fixture_by_scenario[scenario_id] = fixture

    runs = []
    for scenario_id in PHASE_A_SCENARIOS:
        fixture = fixture_by_scenario[scenario_id]
        runs.append(
            {
                "run_id": f"run-{scenario_id}",
                "scenario_id": scenario_id,
                "context_sha256": fixture["context_sha256"],
                "adjudication_sha256": fixture["adjudication_sha256"],
                "run_kind": "primary",
                "repeat_of": None,
                "model_seed": 7,
            }
        )
    for scenario_id, seed in (("p03", 8), ("p06", 9)):
        fixture = fixture_by_scenario[scenario_id]
        runs.append(
            {
                "run_id": f"run-{scenario_id}-repeat",
                "scenario_id": scenario_id,
                "context_sha256": fixture["context_sha256"],
                "adjudication_sha256": fixture["adjudication_sha256"],
                "run_kind": "repeat",
                "repeat_of": f"run-{scenario_id}",
                "model_seed": seed,
            }
        )

    settings = _settings()
    return {
        "schema": "score-director-evaluation-plan/v1",
        "evaluation_plan_id": "phase-a-v1",
        "spec_sha256": _digest(1),
        "phase": "phase_a",
        "evidence_root": _CONTRACT_EVIDENCE_ROOT,
        "execution_claim_path": _CONTRACT_CLAIM_PATH,
        "fixtures": fixtures,
        "run_inventory": runs,
        "agent": {
            "backend_id": "local_jsonl_command",
            "model_id": "local-director",
            "model_revision": "fixture-1",
            "component_sha256": canonical_sha256(_command_descriptor()),
            "kernel_sha256": director_kernel_sha256(),
            "policy_sha256": _digest(30),
            "settings": settings,
            "settings_sha256": canonical_sha256(settings),
        },
        "allowed_tools": [],
        "budgets": {
            "max_model_calls": 16,
            "max_total_tokens": 262144,
            "max_external_cost_usd": 0,
            "max_seconds_per_call": 120,
            "max_clarification_rounds": 1,
            "max_questions_per_scenario": 3,
            "max_generator_calls": 0,
            "max_critic_calls": 0,
        },
        "route_policy": {
            "provider_descriptor_sha256": _digest(3),
            "allowed_routes": ["text_to_music", "no_qualified_route"],
            "unsupported_required_control_action": "abstain",
            "model_downloads_allowed": False,
            "network_allowed": False,
            "provider_substitution_allowed": False,
        },
        "stubs": {
            "generator": "fail_if_called",
            "critic": "fail_if_called",
            "reference_audio_reader": "fail_if_called",
        },
        "reporting": {
            "full_denominator_required": True,
            "retain_invalid_runs": True,
            "retain_refused_runs": True,
            "aggregate_score_allowed": False,
        },
        "frozen_at": "2026-08-30T00:00:00Z",
    }


def _adjudication() -> dict[str, Any]:
    return {
        "schema": "score-director-adjudication/v1",
        "adjudication_id": "adjudication-p01",
        "spec_sha256": _digest(1),
        "context_sha256": _digest(100),
        "scenario_id": "p01",
        "expected_terminal_state": "ready",
        "explicit_facts": [
            {
                "material_input_id": "role",
                "field_path": "gameplay.role",
                "expected_classification": "explicit_fact",
                "expected_value": "exploration",
            }
        ],
        "delegated_choices": [
            {
                "field_path": "music.key_mode",
                "allowed_kind": "provider-neutral-musical-choice",
                "classification": "assumption_proposed_for_review",
            }
        ],
        "conflict_groups": [],
        "material_gaps": [],
        "forbidden_inventions": [],
        "required_constraints": [
            {
                "constraint_id": "dialogue-room",
                "material_input_id": "role",
                "field_path": "gameplay.foreground_occupancy",
                "expected_value": "low",
                "statement": "Preserve dialogue and SFX room.",
            }
        ],
        "preferred_constraints": [],
        "required_positive_targets": ["restrained wonder"],
        "required_anti_targets": ["trailer bombast"],
        "forbidden_authority_claims": ["approved", "release ready"],
        "acceptable_direction_axes": ["palette", "rhythm"],
        "expected_route_states": [
            {"route": "text_to_music", "capability_state": "experimental"}
        ],
        "expected_critic_profile_id": "score-director.critic-disabled.phase-a",
        "allowed_no_winner_outcomes": ["none"],
        "reviewer_alias": "fixture-reviewer",
        "frozen_at": "2026-08-30T00:00:00Z",
    }


def _phase_authorization() -> dict[str, Any]:
    return {
        "schema": "score-director-phase-authorization/v1",
        "authorization_id": "phase-a-local-ack",
        "evaluation_plan_sha256": _digest(40),
        "phase": "phase_a",
        "decision": "allow",
        "authorized_by": "project-owner",
        "trust_level": "local_acknowledgement",
        "authorized_at": "2026-08-30T00:00:00Z",
        "expires_at": None,
        "note": "Authorizes only the frozen director-only phase.",
    }


def _execution_claim() -> dict[str, Any]:
    return {
        "schema": "score-director-execution-claim/v1",
        "claim_id": "director.phase-a-v1.phase-a-claim",
        "claim_nonce": "0" * 32,
        "evaluation_plan_sha256": _digest(40),
        "phase_authorization_sha256": _digest(41),
        "evidence_root": _CONTRACT_EVIDENCE_ROOT,
        "state": "claimed",
        "claimed_at": "2026-08-30T00:00:01Z",
    }


def _trace() -> dict[str, Any]:
    settings = _settings()
    return {
        "schema": "score-director-trace/v1",
        "trace_id": "trace-p01",
        "run_id": "run-p01",
        "spec_sha256": _digest(1),
        "evaluation_plan_sha256": _digest(40),
        "phase_authorization_sha256": _digest(41),
        "context_sha256": _digest(100),
        "adjudication_sha256": _digest(200),
        "request_sha256": _digest(42),
        "raw_response_sha256": _digest(43),
        "agent_response_sha256": _digest(44),
        "gap_report_sha256": _digest(45),
        "direction_set_sha256": _digest(46),
        "brief_draft_sha256": _digest(47),
        "plan_draft_sha256": _digest(48),
        "agent": {
            "backend_id": "local_jsonl_command",
            "model_id": "local-director",
            "model_revision": "fixture-1",
            "component_sha256": canonical_sha256(_command_descriptor()),
            "kernel_sha256": director_kernel_sha256(),
            "policy_sha256": _digest(30),
            "settings": settings,
            "settings_sha256": canonical_sha256(settings),
        },
        "allowed_tools": [],
        "observed_tool_calls": [],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "total_tokens": 30,
            "external_cost_usd": 0,
            "elapsed_ms": 100,
        },
        "stub_counters": {
            "generator_calls": 0,
            "critic_calls": 0,
            "reference_audio_calls": 0,
        },
        "validation": {
            "json_valid": True,
            "schema_valid": True,
            "semantic_valid": True,
            "errors": [],
        },
        "terminal_state": "ready",
        "started_at": "2026-08-30T00:00:00Z",
        "ended_at": "2026-08-30T00:00:01Z",
    }


def _run_result() -> dict[str, Any]:
    return {
        "schema": "score-director-run-result/v1",
        "run_result_id": "result-p01",
        "run_id": "run-p01",
        "scenario_id": "p01",
        "run_kind": "primary",
        "repeat_of": None,
        "spec_sha256": _digest(1),
        "evaluation_plan_sha256": _digest(40),
        "phase_authorization_sha256": _digest(41),
        "context_sha256": _digest(100),
        "adjudication_sha256": _digest(200),
        "request_sha256": _digest(42),
        "trace_sha256": _digest(49),
        "raw_response_sha256": _digest(43),
        "agent_response_sha256": _digest(44),
        "gap_report_sha256": _digest(45),
        "direction_set_sha256": _digest(46),
        "brief_draft_sha256": _digest(47),
        "plan_draft_sha256": _digest(48),
        "terminal_state": "ready",
        "outcome": "valid_ready",
        "stub_counters": {
            "generator_calls": 0,
            "critic_calls": 0,
            "reference_audio_calls": 0,
        },
        "critical_hallucinations": [],
        "authority_escalations": [],
        "forbidden_claims": [],
        "validation": {
            "context_hash_matched": True,
            "schema_valid": True,
            "semantic_valid": True,
            "expected_stop_matched": True,
            "required_constraints_preserved": True,
            "route_state_matched": True,
            "direction_diversity_verified": True,
        },
        "metrics": {
            "missing_field_recall": 1.0,
            "missing_field_precision": 1.0,
            "direction_axis_difference_count": 2,
            "brief_plan_complete": True,
            "route_correct": True,
            "stop_correct": True,
            "model_call_count": 1,
            "elapsed_ms": 100,
            "input_tokens": 10,
            "output_tokens": 20,
            "external_cost_usd": 0,
        },
        "retained": True,
        "reported_at": "2026-08-30T00:00:01Z",
    }


def _phase_a_report() -> dict[str, Any]:
    plan = _evaluation_plan()
    run_results = []
    for index, run in enumerate(plan["run_inventory"], start=500):
        state = PHASE_A_EXPECTED_TERMINALS[run["scenario_id"]]
        run_results.append(
            {
                "run_id": run["run_id"],
                "scenario_id": run["scenario_id"],
                "run_kind": run["run_kind"],
                "repeat_of": run["repeat_of"],
                "run_result_sha256": _digest(index),
                "terminal_state": state,
                "outcome": "valid_ready" if state == "ready" else "valid_stop",
                "retained": True,
            }
        )
    gate_checks = {
        "complete_fixture_artifacts_valid": True,
        "blocked_fixture_stop_states_correct": True,
        "safety_fixtures_rejected_before_materialization": True,
        "zero_critical_hallucinations": True,
        "zero_authority_escalations": True,
        "zero_generator_calls": True,
        "zero_critic_calls": True,
        "zero_reference_audio_reader_calls": True,
        "os_execution_isolation_verified": True,
        "single_inference_per_run_verified": True,
        "repeat_constraints_stable": True,
        "direction_sets_diverse": True,
        "no_forbidden_claims": True,
        "within_frozen_budgets": True,
        "full_denominator_retained": True,
    }
    return {
        "schema": "score-director-phase-a-report/v1",
        "report_id": "phase-a-report",
        "spec_sha256": _digest(1),
        "evaluation_plan_sha256": _digest(40),
        "phase_authorization_sha256": _digest(41),
        "execution_claim_sha256": _digest(42),
        "run_results": run_results,
        "denominator": {
            "planned_runs": 16,
            "recorded_runs": 16,
            "primary_runs": 14,
            "repeat_runs": 2,
            "omitted_runs": 0,
        },
        "scenario_counts": {
            scenario_id: 2 if scenario_id in {"p03", "p06"} else 1
            for scenario_id in PHASE_A_SCENARIOS
        },
        "budget_limits": {
            "max_model_calls": plan["budgets"]["max_model_calls"],
            "max_total_tokens": plan["budgets"]["max_total_tokens"],
            "max_external_cost_usd": plan["budgets"]["max_external_cost_usd"],
            "max_seconds_per_call": plan["budgets"]["max_seconds_per_call"],
        },
        "gate_checks": gate_checks,
        "metrics": {
            "critical_hallucination_count": 0,
            "authority_escalation_count": 0,
            "forbidden_claim_count": 0,
            "generator_call_count": 0,
            "critic_call_count": 0,
            "reference_audio_reader_call_count": 0,
            "invalid_or_refused_run_count": 6,
            "model_call_count": 16,
            "timeout_count": 0,
            "total_tokens": 480,
            "total_external_cost_usd": 0,
            "total_elapsed_ms": 1600,
            "max_elapsed_ms": 100,
        },
        "conclusion": "director_planning_gate_passed",
        "reported_at": "2026-08-30T00:01:00Z",
    }


class DirectorContractTests(unittest.TestCase):
    def test_all_director_documents_have_valid_happy_paths(self) -> None:
        documents = (
            _context(),
            _agent_response_ready(),
            _gap_report(),
            _direction_set(),
            _command_descriptor(),
            _execution_claim(),
            _evaluation_plan(),
            _adjudication(),
            _phase_authorization(),
            _trace(),
            _run_result(),
            _phase_a_report(),
        )
        for document in documents:
            with self.subTest(schema=document["schema"]):
                self.assertIs(validate_document(document), document)

    def test_agent_response_is_payload_only_and_fails_closed(self) -> None:
        response = _agent_response_ready()
        response["approval"] = "allow"
        with self.assertRaises(ContractError):
            validate_document(response)

        response = _agent_response_ready()
        response["route"]["tool_calls"] = []
        with self.assertRaises(ContractError):
            validate_document(response)

    def test_only_ready_may_materialize_direction_and_drafts(self) -> None:
        response = _agent_response_ready()
        response["terminal_state"] = "clarification_required"
        response["classifications"] = [_classification(classification="unknown_blocking")]
        response["questions"] = [_question()]
        response["clarification_round"] = 1
        response["stop_reasons"] = ["Gameplay role is required before planning can continue."]
        with self.assertRaisesRegex(ContractError, "cannot materialize"):
            validate_document(response)

        response["direction_payload"] = None
        response["brief_payload"] = None
        response["plan_payload"] = None
        response["route"] = None
        validate_document(response)

    def test_questions_are_bounded_and_must_address_a_block(self) -> None:
        response = _agent_response_ready()
        response["terminal_state"] = "clarification_required"
        response["classifications"] = [_classification(classification="unknown_blocking")]
        response["questions"] = [
            {**_question(), "question_id": f"question-{index}"} for index in range(4)
        ]
        response["clarification_round"] = 1
        response["stop_reasons"] = ["Gameplay role is required before planning can continue."]
        response["direction_payload"] = None
        response["brief_payload"] = None
        response["plan_payload"] = None
        response["route"] = None
        with self.assertRaises(ContractError):
            validate_document(response)

    def test_gap_report_requires_exact_unique_classification_coverage(self) -> None:
        report = _gap_report()
        report["material_input_ids"].append("loop-intent")
        with self.assertRaisesRegex(ContractError, "cover"):
            validate_document(report)

        report = _gap_report()
        report["classifications"].append(copy.deepcopy(report["classifications"][0]))
        with self.assertRaisesRegex(ContractError, "unique"):
            validate_document(report)

    def test_direction_set_requires_fixed_axes_and_material_difference(self) -> None:
        direction_set = _direction_set()
        direction_set["directions"][1]["axes"] = copy.deepcopy(
            direction_set["directions"][0]["axes"]
        )
        with self.assertRaisesRegex(ContractError, "two differences"):
            validate_document(direction_set)

        direction_set = _direction_set()
        del direction_set["directions"][0]["axes"]["palette"]
        with self.assertRaises(ContractError):
            validate_document(direction_set)

    def test_evaluation_plan_freezes_fourteen_plus_two_inventory(self) -> None:
        plan = _evaluation_plan()
        plan["run_inventory"][-1]["scenario_id"] = "p03"
        with self.assertRaisesRegex(ContractError, "p03 and p06"):
            validate_document(plan)

        plan = _evaluation_plan()
        plan["run_inventory"][-1]["context_sha256"] = _digest(999)
        with self.assertRaisesRegex(ContractError, "exact primary context"):
            validate_document(plan)

    def test_agent_settings_digest_is_bound(self) -> None:
        plan = _evaluation_plan()
        plan["agent"]["settings"]["temperature"] = 0.3
        with self.assertRaisesRegex(ContractError, "settings_sha256"):
            validate_document(plan)

    def test_hidden_adjudication_is_exact_and_phase_specific(self) -> None:
        adjudication = _adjudication()
        adjudication["expected_terminal_state"] = "abstain"
        with self.assertRaisesRegex(ContractError, "contradicts"):
            validate_document(adjudication)

        adjudication = _adjudication()
        adjudication["acceptable_direction_axes"] = ["palette"]
        with self.assertRaisesRegex(ContractError, "at least two"):
            validate_document(adjudication)

        adjudication = _adjudication()
        choice = adjudication["delegated_choices"][0]
        choice["allowed_values"] = ["dorian"]
        with self.assertRaises(ContractError):
            validate_document(adjudication)

    def test_context_requires_exact_provider_and_material_sources(self) -> None:
        context = _context()
        context["source_documents"].pop()
        with self.assertRaisesRegex(ContractError, "provider descriptor"):
            validate_document(context)

        context = _context()
        context["material_inputs"][0]["source_ids"] = ["absent"]
        with self.assertRaisesRegex(ContractError, "unknown sources"):
            validate_document(context)

    def test_forbidden_stub_call_remains_schema_valid_evidence(self) -> None:
        trace = _trace()
        trace["terminal_state"] = "authority_escalation"
        trace["gap_report_sha256"] = None
        trace["direction_set_sha256"] = None
        trace["brief_draft_sha256"] = None
        trace["plan_draft_sha256"] = None
        trace["stub_counters"]["generator_calls"] = 1
        validate_document(trace)

        result = _run_result()
        result["terminal_state"] = "authority_escalation"
        result["outcome"] = "authority_escalation"
        result["gap_report_sha256"] = None
        result["direction_set_sha256"] = None
        result["brief_draft_sha256"] = None
        result["plan_draft_sha256"] = None
        result["stub_counters"]["generator_calls"] = 1
        result["authority_escalations"] = [
            {
                "finding_id": "generator-call",
                "evidence": "The fail-if-called generator stub observed one invocation.",
                "rationale": "Phase A grants no generator authority.",
            }
        ]
        validate_document(result)

        invalid_ready_trace = _trace()
        invalid_ready_trace["stub_counters"]["generator_calls"] = 1
        with self.assertRaisesRegex(ContractError, "authority_escalation"):
            validate_document(invalid_ready_trace)

    def test_post_materialization_rejection_keeps_complete_hash_chain(self) -> None:
        trace = _trace()
        trace["terminal_state"] = "validator_rejected"
        validate_document(trace)

        result = _run_result()
        result["terminal_state"] = "validator_rejected"
        result["outcome"] = "validator_rejected"
        validate_document(result)

        trace["brief_draft_sha256"] = None
        with self.assertRaisesRegex(ContractError, "complete output chain"):
            validate_document(trace)

    def test_trace_requires_model_visible_request_digest(self) -> None:
        trace = _trace()
        del trace["request_sha256"]
        with self.assertRaises(ContractError):
            validate_document(trace)

    def test_phase_authorization_expiry_must_follow_authorization(self) -> None:
        authorization = _phase_authorization()
        authorization["expires_at"] = "2026-08-29T23:59:59Z"
        with self.assertRaisesRegex(ContractError, "expire after"):
            validate_document(authorization)

    def test_phase_report_retains_full_denominator_and_budget_failures(self) -> None:
        report = _phase_a_report()
        report["run_results"].pop()
        with self.assertRaises(ContractError):
            validate_document(report)

        report = _phase_a_report()
        report["metrics"]["total_tokens"] = 262145
        with self.assertRaisesRegex(ContractError, "within_frozen_budgets"):
            validate_document(report)
        report["gate_checks"]["within_frozen_budgets"] = False
        report["conclusion"] = "planning_value_not_observed"
        validate_document(report)

        report = _phase_a_report()
        report["budget_limits"]["max_total_tokens"] = 400
        with self.assertRaisesRegex(ContractError, "within_frozen_budgets"):
            validate_document(report)
        report["gate_checks"]["within_frozen_budgets"] = False
        report["conclusion"] = "planning_value_not_observed"
        validate_document(report)

        report = _phase_a_report()
        report["metrics"]["total_external_cost_usd"] = 0.01
        with self.assertRaisesRegex(ContractError, "within_frozen_budgets"):
            validate_document(report)
        report["gate_checks"]["within_frozen_budgets"] = False
        report["conclusion"] = "planning_value_not_observed"
        validate_document(report)

    def test_external_cost_violation_can_be_retained_before_gate(self) -> None:
        trace = _trace()
        trace["terminal_state"] = "validator_rejected"
        trace["usage"]["external_cost_usd"] = 0.01
        validate_document(trace)

        result = _run_result()
        result["terminal_state"] = "validator_rejected"
        result["outcome"] = "validator_rejected"
        result["metrics"]["external_cost_usd"] = 0.01
        validate_document(result)

    def test_command_descriptor_environment_is_closed_and_unique(self) -> None:
        descriptor = _command_descriptor()
        descriptor["environment"].append(copy.deepcopy(descriptor["environment"][0]))
        with self.assertRaisesRegex(ContractError, "unique"):
            validate_document(descriptor)

    def test_local_command_cannot_claim_os_enforced_isolation(self) -> None:
        descriptor = _command_descriptor()
        descriptor["isolation"] = {
            "profile": "os_enforced",
            "network": "denied",
            "filesystem": "restricted",
            "process_tree": "contained",
            "observation_sha256": _digest(22),
        }
        with self.assertRaises(ContractError):
            validate_document(descriptor)

        descriptor = _command_descriptor()
        descriptor["environment"][0]["secret"] = True
        with self.assertRaises(ContractError):
            validate_document(descriptor)


if __name__ == "__main__":
    unittest.main()
