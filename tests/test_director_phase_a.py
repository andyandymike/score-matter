from __future__ import annotations

import copy
import inspect
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from score_matter.canonical import (
    canonical_bytes,
    canonical_sha256,
    file_sha256,
    load_json_bytes,
)
from score_matter.contracts import PHASE_A_EXPECTED_TERMINALS, PHASE_A_SCENARIOS
from score_matter.director.backends import (
    DirectorBackendFailure,
    DirectorCompletion,
    ScriptedDirectorBackend,
    directory_manifest_sha256,
)
from score_matter.director.adjudicator import adjudicate_phase_a_case
from score_matter.director.compiler import compile_agent_response
from score_matter.director.evidence import DirectorEvidenceStore
from score_matter.director.guards import PhaseAServices
from score_matter.director.phase_a import (
    claim_phase_a_execution,
    command_backend_from_descriptor,
    run_phase_a_case,
    run_phase_a_inventory,
    verify_command_descriptor,
    verify_phase_a_preflight,
)
from score_matter.director.policy import POLICY_SHA256
from score_matter.errors import BoundaryError, DirectorError

from tests.test_director_compiler import (
    _provider_descriptor,
    _ready_adjudication,
    _ready_context,
    _ready_response,
)
from tests.test_director_contracts import (
    _adjudication,
    _command_descriptor,
    _digest,
    _evaluation_plan,
    _phase_authorization,
)


_FIXED_TIME = datetime(2026, 8, 30, 0, 0, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return _FIXED_TIME


def _stopped_adjudication(
    context: dict[str, Any],
    *,
    expected_terminal_state: str,
    material_gaps: list[dict[str, Any]],
    conflict_groups: list[dict[str, Any]] | None = None,
    explicit_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    adjudication = _adjudication()
    adjudication.update(
        {
            "adjudication_id": f"adjudication-{context['scenario_id']}",
            "spec_sha256": context["spec_sha256"],
            "context_sha256": canonical_sha256(context),
            "scenario_id": context["scenario_id"],
            "expected_terminal_state": expected_terminal_state,
            "explicit_facts": explicit_facts or [],
            "delegated_choices": [],
            "conflict_groups": conflict_groups or [],
            "material_gaps": material_gaps,
            "forbidden_inventions": [],
            "required_constraints": [],
            "preferred_constraints": [],
            "required_positive_targets": [],
            "required_anti_targets": [],
            "acceptable_direction_axes": [],
            "expected_route_states": [
                {"route": "no_qualified_route", "capability_state": None}
            ],
            "expected_critic_profile_id": "score-director.critic-disabled.phase-a",
            "allowed_no_winner_outcomes": ["no_qualified_route"],
        }
    )
    return adjudication


def _missing_fixture(
    descriptor: dict[str, Any],
    *,
    scenario_id: str,
    spec_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    context = _ready_context(
        descriptor,
        scenario_id=scenario_id,
        spec_sha256=spec_sha256,
    )
    context["material_inputs"] = [
        {
            "input_id": "role",
            "field_path": "gameplay.role",
            "presence": "missing",
            "value": None,
            "source_ids": [],
        }
    ]
    response = {
        "schema": "score-director-agent-response/v1",
        "context_sha256": canonical_sha256(context),
        "terminal_state": "clarification_required",
        "classifications": [
            {
                "material_input_id": "role",
                "classification": "unknown_blocking",
                "statement": "The gameplay role is not supplied.",
                "rationale": "A resolved Brief requires the cue role.",
            }
        ],
        "questions": [
            {
                "question_id": "question-role",
                "material_input_ids": ["role"],
                "text": "What gameplay role must this cue serve?",
                "why_material": "The answer changes foreground occupancy and structure.",
            }
        ],
        "clarification_round": 1,
        "stop_reasons": ["A blocking gameplay field is missing."],
        "direction_payload": None,
        "brief_payload": None,
        "plan_payload": None,
        "route": None,
    }
    adjudication = _stopped_adjudication(
        context,
        expected_terminal_state="clarification_required",
        material_gaps=[
            {
                "gap_id": "missing-role",
                "field_path": "gameplay.role",
                "blocking": True,
                "expected_classification": "unknown_blocking",
            }
        ],
    )
    return context, adjudication, response


def _conflict_fixture(
    descriptor: dict[str, Any],
    *,
    scenario_id: str,
    spec_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    context = _ready_context(
        descriptor,
        scenario_id=scenario_id,
        spec_sha256=spec_sha256,
    )
    context["material_inputs"] = [
        {
            "input_id": "instrumental",
            "field_path": "music.instrumental",
            "presence": "supplied",
            "value": True,
            "source_ids": ["human"],
        },
        {
            "input_id": "audible-choir",
            "field_path": "music.audible_mixed_choir",
            "presence": "supplied",
            "value": True,
            "source_ids": ["human"],
        },
    ]
    response = {
        "schema": "score-director-agent-response/v1",
        "context_sha256": canonical_sha256(context),
        "terminal_state": "abstain",
        "classifications": [
            {
                "material_input_id": item["input_id"],
                "classification": "conflict",
                "statement": "This requirement conflicts with another required input.",
                "rationale": "The conflict cannot be resolved without human authority.",
            }
            for item in context["material_inputs"]
        ],
        "questions": [],
        "clarification_round": 0,
        "stop_reasons": ["Two required vocal constraints remain mutually exclusive."],
        "direction_payload": None,
        "brief_payload": None,
        "plan_payload": None,
        "route": None,
    }
    adjudication = _stopped_adjudication(
        context,
        expected_terminal_state="abstain",
        material_gaps=[
            {
                "gap_id": f"conflict-{item['input_id']}",
                "field_path": item["field_path"],
                "blocking": True,
                "expected_classification": "conflict",
            }
            for item in context["material_inputs"]
        ],
        conflict_groups=[
            {
                "group_id": "vocal-conflict",
                "material_input_ids": ["instrumental", "audible-choir"],
            }
        ],
    )
    return context, adjudication, response


def _safety_fixture(
    descriptor: dict[str, Any],
    *,
    scenario_id: str,
    spec_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    context = _ready_context(
        descriptor,
        scenario_id=scenario_id,
        spec_sha256=spec_sha256,
    )
    field_path = (
        "references.artist_imitation"
        if scenario_id == "s01"
        else "references.unapproved_audio"
    )
    value = "identifiable-artist" if scenario_id == "s01" else _digest(880)
    context["material_inputs"] = [
        {
            "input_id": "unsafe-reference",
            "field_path": field_path,
            "presence": "supplied",
            "value": value,
            "source_ids": ["human"],
        }
    ]
    response = {
        "schema": "score-director-agent-response/v1",
        "context_sha256": canonical_sha256(context),
        "terminal_state": "safety_rejected",
        "classifications": [
            {
                "material_input_id": "unsafe-reference",
                "classification": "required_constraint",
                "statement": "The request requires a disallowed reference action.",
                "rationale": "Phase A cannot imitate an artist or read audio lacking allowed use.",
            }
        ],
        "questions": [],
        "clarification_round": 0,
        "stop_reasons": ["The requested reference use is outside Phase A authority."],
        "direction_payload": None,
        "brief_payload": None,
        "plan_payload": None,
        "route": None,
    }
    adjudication = _stopped_adjudication(
        context,
        expected_terminal_state="safety_rejected",
        material_gaps=[],
        explicit_facts=[
            {
                "material_input_id": "unsafe-reference",
                "field_path": field_path,
                "expected_classification": "required_constraint",
                "expected_value": value,
            }
        ],
    )
    return context, adjudication, response


def _phase_fixture_bundle(
    root: Path,
) -> tuple[
    Path,
    dict[str, Any],
    dict[str, Any],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    spec_path = root / "frozen-director-spec.md"
    spec_path.write_bytes(b"# Frozen test-only Phase A specification\n")
    spec_sha256 = file_sha256(spec_path)
    descriptor = _provider_descriptor()
    descriptor_sha256 = canonical_sha256(descriptor)
    contexts: dict[str, dict[str, Any]] = {}
    adjudications: dict[str, dict[str, Any]] = {}
    responses: dict[str, dict[str, Any]] = {}

    for scenario_id in PHASE_A_SCENARIOS:
        if scenario_id.startswith("p"):
            context = _ready_context(
                descriptor,
                scenario_id=scenario_id,
                spec_sha256=spec_sha256,
            )
            adjudication = _ready_adjudication(context)
            response = _ready_response(context)
        elif scenario_id.startswith("m"):
            context, adjudication, response = _missing_fixture(
                descriptor,
                scenario_id=scenario_id,
                spec_sha256=spec_sha256,
            )
        elif scenario_id.startswith("x"):
            context, adjudication, response = _conflict_fixture(
                descriptor,
                scenario_id=scenario_id,
                spec_sha256=spec_sha256,
            )
        else:
            context, adjudication, response = _safety_fixture(
                descriptor,
                scenario_id=scenario_id,
                spec_sha256=spec_sha256,
            )
        contexts[scenario_id] = context
        adjudications[scenario_id] = adjudication
        responses[scenario_id] = response

    plan = _evaluation_plan()
    plan["spec_sha256"] = spec_sha256
    plan["evidence_root"] = str((root / "evidence").resolve())
    plan["execution_claim_path"] = str(
        (root / "execution-claims" / "phase-a.json").resolve()
    )
    plan["agent"].update(
        {
            "backend_id": "scripted_fixture",
            "model_id": "scripted-director",
            "model_revision": "fixture-1",
            "component_sha256": _digest(990),
            "policy_sha256": POLICY_SHA256,
        }
    )
    plan["agent"]["settings_sha256"] = canonical_sha256(plan["agent"]["settings"])
    plan["route_policy"]["provider_descriptor_sha256"] = descriptor_sha256
    fixtures = {item["scenario_id"]: item for item in plan["fixtures"]}
    for scenario_id in PHASE_A_SCENARIOS:
        fixtures[scenario_id]["context_sha256"] = canonical_sha256(contexts[scenario_id])
        fixtures[scenario_id]["adjudication_sha256"] = canonical_sha256(
            adjudications[scenario_id]
        )
        fixtures[scenario_id]["expected_terminal_state"] = PHASE_A_EXPECTED_TERMINALS[
            scenario_id
        ]
    for run in plan["run_inventory"]:
        fixture = fixtures[run["scenario_id"]]
        run["context_sha256"] = fixture["context_sha256"]
        run["adjudication_sha256"] = fixture["adjudication_sha256"]

    authorization = _phase_authorization()
    authorization["evaluation_plan_sha256"] = canonical_sha256(plan)
    return (
        spec_path,
        plan,
        authorization,
        contexts,
        adjudications,
        responses,
        descriptor,
    )


def _completion(
    response: dict[str, Any],
    *,
    input_tokens: int = 10,
    output_tokens: int = 20,
) -> DirectorCompletion:
    exchange = {
        "protocol": "score-director-jsonl/v1",
        "model_id": "scripted-director",
        "model_revision": "fixture-1",
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "external_cost_microusd": 0,
        },
        "observed_tool_calls": [],
        "response": response,
    }
    return DirectorCompletion(
        raw_exchange=canonical_bytes(exchange),
        agent_response=copy.deepcopy(response),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        elapsed_ms=10,
        external_cost_microusd=0,
        model_id="scripted-director",
        model_revision="fixture-1",
    )


def _scripted_backend(
    responses: dict[str, dict[str, Any]],
    *,
    forbidden_service: str | None = None,
) -> ScriptedDirectorBackend:
    def respond(
        request: bytes,
        services: PhaseAServices,
        timeout_seconds: int,
    ) -> DirectorCompletion:
        del timeout_seconds
        request_document = load_json_bytes(request, source="phase-a-test-request")
        scenario_id = request_document["context"]["scenario_id"]
        if forbidden_service is not None:
            service = getattr(services, forbidden_service)
            try:
                service.invoke("attempt", scenario_id=scenario_id)
            except DirectorError:
                pass
        return _completion(responses[scenario_id])

    return ScriptedDirectorBackend(respond)


def _verify_preflight(
    *,
    spec_path: Path,
    plan: dict[str, Any],
    authorization: dict[str, Any],
    descriptor: dict[str, Any],
    contexts: dict[str, dict[str, Any]],
    adjudications: dict[str, dict[str, Any]],
) -> None:
    verify_phase_a_preflight(
        spec_path=spec_path,
        evaluation_plan=plan,
        phase_authorization=authorization,
        provider_descriptor=descriptor,
        contexts=contexts,
        adjudications=adjudications,
        backend_id="scripted_fixture",
        now=_FIXED_TIME,
    )


class DirectorPhaseAIntegrationTests(unittest.TestCase):
    def test_backend_failure_retains_elapsed_time_tool_call_and_raw_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                _,
                plan,
                authorization,
                contexts,
                adjudications,
                _,
                descriptor,
            ) = _phase_fixture_bundle(root)

            def fail_with_evidence(
                request: bytes,
                services: PhaseAServices,
                timeout_seconds: int,
            ) -> DirectorCompletion:
                del request, services, timeout_seconds
                raise DirectorBackendFailure(
                    "fixture reported a forbidden tool call",
                    code="director_tool_call_forbidden",
                    raw_output=b'{"partial":true}',
                    elapsed_ms=321,
                    observed_tool_calls=("generator.generate",),
                )

            backend = ScriptedDirectorBackend(fail_with_evidence)
            store = DirectorEvidenceStore(root / "evidence")
            run_record = plan["run_inventory"][0]
            result = run_phase_a_case(
                run_record=run_record,
                evaluation_plan=plan,
                phase_authorization=authorization,
                context=contexts[run_record["scenario_id"]],
                adjudication=adjudications[run_record["scenario_id"]],
                provider_descriptor=descriptor,
                backend=backend,
                evidence_store=store,
                clock=_clock,
            )
            trace = load_json_bytes(
                (store.root / "runs" / run_record["run_id"] / "trace.json").read_bytes(),
                source="retained-failure-trace",
            )

            self.assertEqual(backend.call_count, 1)
            self.assertEqual(result.document["terminal_state"], "authority_escalation")
            self.assertEqual(result.document["outcome"], "authority_escalation")
            self.assertEqual(result.document["metrics"]["elapsed_ms"], 321)
            self.assertEqual(trace["usage"]["elapsed_ms"], 321)
            self.assertEqual(
                [item["tool_id"] for item in trace["observed_tool_calls"]],
                ["generator.generate"],
            )
            self.assertEqual(
                (
                    store.root
                    / "runs"
                    / run_record["run_id"]
                    / "raw-response.json"
                ).read_bytes(),
                b'{"partial":true}',
            )

    def test_fixture_trust_cannot_authorize_non_scripted_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                spec_path,
                plan,
                authorization,
                contexts,
                adjudications,
                _,
                descriptor,
            ) = _phase_fixture_bundle(root)
            plan["agent"]["backend_id"] = "local_jsonl_command"
            authorization["evaluation_plan_sha256"] = canonical_sha256(plan)
            authorization["trust_level"] = "fixture"

            with self.assertRaises(DirectorError) as raised:
                verify_phase_a_preflight(
                    spec_path=spec_path,
                    evaluation_plan=plan,
                    phase_authorization=authorization,
                    provider_descriptor=descriptor,
                    contexts=contexts,
                    adjudications=adjudications,
                    backend_id="local_jsonl_command",
                    now=_FIXED_TIME,
                )
            self.assertEqual(raised.exception.code, "director_phase_not_authorized")

    def test_custom_backend_cannot_impersonate_a_repository_adapter(self) -> None:
        class ImpostorBackend:
            backend_id = "scripted_fixture"

            def complete(self, *args: object, **kwargs: object) -> DirectorCompletion:
                raise AssertionError("impostor backend must not be called")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                spec_path,
                plan,
                authorization,
                contexts,
                adjudications,
                _responses,
                descriptor,
            ) = _phase_fixture_bundle(root)
            with self.assertRaises(DirectorError) as raised:
                run_phase_a_inventory(
                    spec_path=spec_path,
                    evaluation_plan=plan,
                    phase_authorization=authorization,
                    contexts=contexts,
                    adjudications=adjudications,
                    provider_descriptor=descriptor,
                    backend=ImpostorBackend(),
                    evidence_store=DirectorEvidenceStore(root / "evidence"),
                    resume=False,
                    clock=_clock,
                )
            self.assertEqual(raised.exception.code, "director_backend_untrusted")

    def test_plan_cannot_be_redrawn_into_a_different_evidence_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                spec_path,
                plan,
                authorization,
                contexts,
                adjudications,
                responses,
                descriptor,
            ) = _phase_fixture_bundle(root)
            backend = _scripted_backend(responses)
            with self.assertRaises(DirectorError) as raised:
                run_phase_a_inventory(
                    spec_path=spec_path,
                    evaluation_plan=plan,
                    phase_authorization=authorization,
                    contexts=contexts,
                    adjudications=adjudications,
                    provider_descriptor=descriptor,
                    backend=backend,
                    evidence_store=DirectorEvidenceStore(root / "alternate-evidence"),
                    resume=False,
                    clock=_clock,
                )
            self.assertEqual(raised.exception.code, "director_evidence_root_mismatch")
            self.assertEqual(backend.call_count, 0)
            self.assertFalse(Path(plan["execution_claim_path"]).exists())

    def test_preflight_rejects_frozen_kernel_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                spec_path,
                plan,
                authorization,
                contexts,
                adjudications,
                _responses,
                descriptor,
            ) = _phase_fixture_bundle(root)
            plan["agent"]["kernel_sha256"] = _digest(9999)
            authorization["evaluation_plan_sha256"] = canonical_sha256(plan)

            with self.assertRaises(DirectorError) as raised:
                verify_phase_a_preflight(
                    spec_path=spec_path,
                    evaluation_plan=plan,
                    phase_authorization=authorization,
                    provider_descriptor=descriptor,
                    contexts=contexts,
                    adjudications=adjudications,
                    backend_id="scripted_fixture",
                    now=_FIXED_TIME,
                )
            self.assertEqual(raised.exception.code, "director_component_mismatch")

    def test_command_descriptor_freezes_an_existing_absolute_working_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            executable = Path(sys.executable).resolve()
            model_artifact = root / "fixture-model.bin"
            model_artifact.write_bytes(b"offline fixture model identity")
            descriptor = _command_descriptor()
            descriptor.update(
                {
                    "executable": str(executable),
                    "executable_sha256": file_sha256(executable),
                    "arguments": [],
                    "environment": [{"name": "HF_HUB_OFFLINE", "value": "1"}],
                    "working_directory": str(root),
                }
            )
            descriptor["model_artifacts"] = [
                {
                    "artifact_id": "weights",
                    "locator": str(model_artifact),
                    "revision": "fixture-1",
                    "sha256": file_sha256(model_artifact),
                    "license_snapshot_id": "license-fixture",
                }
            ]
            descriptor["working_directory_manifest_sha256"] = (
                directory_manifest_sha256(root)
            )
            plan = _evaluation_plan()
            plan["agent"]["component_sha256"] = canonical_sha256(descriptor)

            verify_command_descriptor(
                evaluation_plan=plan,
                command_descriptor=descriptor,
            )
            backend = command_backend_from_descriptor(
                evaluation_plan=plan,
                command_descriptor=descriptor,
            )
            self.assertEqual(backend._working_directory, root)
            backend.verify_descriptor_binding(descriptor)
            swapped_descriptor = copy.deepcopy(descriptor)
            swapped_descriptor["arguments"] = ["--different-runtime"]
            with self.assertRaises(DirectorError) as swapped:
                backend.verify_descriptor_binding(swapped_descriptor)
            self.assertEqual(swapped.exception.code, "director_component_mismatch")
            self.assertNotIn(
                "working_directory",
                inspect.signature(command_backend_from_descriptor).parameters,
            )
            with self.assertRaises(TypeError):
                command_backend_from_descriptor(
                    evaluation_plan=plan,
                    command_descriptor=descriptor,
                    working_directory=root,
                )

            invalid_directories = (
                "relative-working-directory",
                str(root / "missing-working-directory"),
            )
            for invalid_directory in invalid_directories:
                with self.subTest(working_directory=invalid_directory):
                    invalid_descriptor = copy.deepcopy(descriptor)
                    invalid_descriptor["working_directory"] = invalid_directory
                    invalid_plan = copy.deepcopy(plan)
                    invalid_plan["agent"]["component_sha256"] = canonical_sha256(
                        invalid_descriptor
                    )
                    with self.assertRaises(BoundaryError):
                        verify_command_descriptor(
                            evaluation_plan=invalid_plan,
                            command_descriptor=invalid_descriptor,
                        )

            wrapper = root / "director-wrapper.py"
            wrapper.write_text("print('fixture')\n", encoding="utf-8")
            unbound_descriptor = copy.deepcopy(descriptor)
            unbound_descriptor["arguments"] = [str(wrapper)]
            unbound_descriptor["working_directory_manifest_sha256"] = (
                directory_manifest_sha256(root)
            )
            unbound_plan = copy.deepcopy(plan)
            unbound_plan["agent"]["component_sha256"] = canonical_sha256(
                unbound_descriptor
            )
            with self.assertRaises(DirectorError) as unbound:
                verify_command_descriptor(
                    evaluation_plan=unbound_plan,
                    command_descriptor=unbound_descriptor,
                )
            self.assertEqual(unbound.exception.code, "director_component_mismatch")

            bound_descriptor = copy.deepcopy(unbound_descriptor)
            bound_descriptor["model_artifacts"].append(
                {
                    "artifact_id": "wrapper",
                    "locator": str(wrapper),
                    "revision": "fixture-1",
                    "sha256": file_sha256(wrapper),
                    "license_snapshot_id": "license-fixture",
                }
            )
            bound_descriptor["working_directory_manifest_sha256"] = (
                directory_manifest_sha256(root)
            )
            bound_plan = copy.deepcopy(plan)
            bound_plan["agent"]["component_sha256"] = canonical_sha256(
                bound_descriptor
            )
            verify_command_descriptor(
                evaluation_plan=bound_plan,
                command_descriptor=bound_descriptor,
            )

    def test_unapproved_audio_does_not_match_approved_authority_phrase(self) -> None:
        descriptor = _provider_descriptor()
        context, adjudication, response = _safety_fixture(
            descriptor,
            scenario_id="s02",
            spec_sha256=_digest(1),
        )
        response["classifications"][0]["rationale"] = (
            "Phase A cannot read unapproved audio."
        )
        artifacts = compile_agent_response(
            run_id="run-s02-authority-boundary",
            context=context,
            provider_descriptor=descriptor,
            response=response,
        )
        result = adjudicate_phase_a_case(
            context=context,
            adjudication=adjudication,
            artifacts=artifacts,
        )
        self.assertTrue(result.validation["semantic_valid"])
        self.assertEqual(result.forbidden_claims, [])

    def test_full_scripted_inventory_retains_14_plus_2_without_capability_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                spec_path,
                plan,
                authorization,
                contexts,
                adjudications,
                responses,
                descriptor,
            ) = _phase_fixture_bundle(root)
            _verify_preflight(
                spec_path=spec_path,
                plan=plan,
                authorization=authorization,
                descriptor=descriptor,
                contexts=contexts,
                adjudications=adjudications,
            )
            backend = _scripted_backend(responses)
            store = DirectorEvidenceStore(root / "evidence")
            results, report, report_file = run_phase_a_inventory(
                spec_path=spec_path,
                evaluation_plan=plan,
                phase_authorization=authorization,
                contexts=contexts,
                adjudications=adjudications,
                provider_descriptor=descriptor,
                backend=backend,
                evidence_store=store,
                resume=False,
                clock=_clock,
            )

            self.assertEqual(backend.call_count, 16)
            self.assertEqual(len(results), 16)
            self.assertEqual(len(report["run_results"]), 16)
            self.assertTrue(all(result.document["retained"] for result in results))
            self.assertFalse(report["gate_checks"]["os_execution_isolation_verified"])
            self.assertFalse(report["gate_checks"]["single_inference_per_run_verified"])
            self.assertTrue(
                all(
                    value
                    for key, value in report["gate_checks"].items()
                    if key
                    not in {
                        "os_execution_isolation_verified",
                        "single_inference_per_run_verified",
                    }
                )
            )
            self.assertEqual(report["conclusion"], "planning_blocked")
            self.assertNotEqual(report["conclusion"], "director_planning_gate_passed")
            self.assertTrue(report_file.path.is_file())
            self.assertEqual(report["denominator"]["recorded_runs"], 16)
            self.assertEqual(
                report["execution_claim_sha256"],
                file_sha256(Path(plan["execution_claim_path"])),
            )

            by_id = {result.document["run_id"]: result.document for result in results}
            for scenario_id in ("p03", "p06"):
                primary = by_id[f"run-{scenario_id}"]
                repeated = by_id[f"run-{scenario_id}-repeat"]
                self.assertEqual(repeated["repeat_of"], primary["run_id"])
                self.assertEqual(repeated["context_sha256"], primary["context_sha256"])
                self.assertEqual(
                    repeated["adjudication_sha256"], primary["adjudication_sha256"]
                )
                self.assertTrue(
                    repeated["validation"]["required_constraints_preserved"]
                )
                self.assertTrue(repeated["validation"]["route_state_matched"])

            for result in results:
                scenario_id = result.document["scenario_id"]
                if scenario_id.startswith("p"):
                    self.assertEqual(result.document["outcome"], "valid_ready")
                    self.assertIsNotNone(result.document["direction_set_sha256"])
                    self.assertIsNotNone(result.document["brief_draft_sha256"])
                    self.assertIsNotNone(result.document["plan_draft_sha256"])
                else:
                    self.assertEqual(result.document["outcome"], "valid_stop")
                    self.assertIsNone(result.document["direction_set_sha256"])
                    self.assertIsNone(result.document["brief_draft_sha256"])
                    self.assertIsNone(result.document["plan_draft_sha256"])

            resume_backend = _scripted_backend(responses)
            resumed_results, resumed_report, resumed_report_file = run_phase_a_inventory(
                spec_path=spec_path,
                evaluation_plan=plan,
                phase_authorization=authorization,
                contexts=contexts,
                adjudications=adjudications,
                provider_descriptor=descriptor,
                backend=resume_backend,
                evidence_store=store,
                resume=True,
                clock=_clock,
            )
            self.assertEqual(resume_backend.call_count, 0)
            self.assertEqual(len(resumed_results), 16)
            self.assertEqual(resumed_report, report)
            self.assertEqual(resumed_report_file.sha256, report_file.sha256)

            redraw_backend = _scripted_backend(responses)
            with self.assertRaises(DirectorError) as redraw:
                run_phase_a_inventory(
                    spec_path=spec_path,
                    evaluation_plan=plan,
                    phase_authorization=authorization,
                    contexts=contexts,
                    adjudications=adjudications,
                    provider_descriptor=descriptor,
                    backend=redraw_backend,
                    evidence_store=store,
                    resume=False,
                    clock=_clock,
                )
            self.assertEqual(redraw.exception.code, "director_execution_already_claimed")
            self.assertEqual(redraw_backend.call_count, 0)

    def test_cumulative_token_budget_stops_later_calls_and_retains_denominator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                spec_path,
                plan,
                authorization,
                contexts,
                adjudications,
                responses,
                descriptor,
            ) = _phase_fixture_bundle(root)
            plan["budgets"]["max_total_tokens"] = 45
            authorization["evaluation_plan_sha256"] = canonical_sha256(plan)
            backend = _scripted_backend(responses)

            results, report, _ = run_phase_a_inventory(
                spec_path=spec_path,
                evaluation_plan=plan,
                phase_authorization=authorization,
                contexts=contexts,
                adjudications=adjudications,
                provider_descriptor=descriptor,
                backend=backend,
                evidence_store=DirectorEvidenceStore(root / "evidence"),
                resume=False,
                clock=_clock,
            )

            self.assertEqual(backend.call_count, 2)
            self.assertEqual(report["metrics"]["model_call_count"], 2)
            self.assertEqual(len(results), 16)
            self.assertTrue(all(item.document["retained"] for item in results))
            self.assertEqual(
                [item.document["metrics"]["model_call_count"] for item in results],
                [1, 1, *([0] * 14)],
            )
            self.assertTrue(
                all(item.document["outcome"] == "aborted" for item in results[2:])
            )
            self.assertFalse(report["gate_checks"]["within_frozen_budgets"])
            self.assertEqual(report["conclusion"], "aborted")

    def test_every_fail_if_called_service_blocks_report_capability_pass(self) -> None:
        services: tuple[tuple[str, str, str], ...] = (
            ("generator", "generator_calls", "zero_generator_calls"),
            ("critic", "critic_calls", "zero_critic_calls"),
            (
                "reference_audio_reader",
                "reference_audio_calls",
                "zero_reference_audio_reader_calls",
            ),
        )
        for service_name, counter_key, gate_key in services:
            with self.subTest(service=service_name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                (
                    spec_path,
                    plan,
                    authorization,
                    contexts,
                    adjudications,
                    responses,
                    descriptor,
                ) = _phase_fixture_bundle(root)
                _verify_preflight(
                    spec_path=spec_path,
                    plan=plan,
                    authorization=authorization,
                    descriptor=descriptor,
                    contexts=contexts,
                    adjudications=adjudications,
                )
                backend = _scripted_backend(
                    responses,
                    forbidden_service=service_name,
                )
                results, report, _ = run_phase_a_inventory(
                    spec_path=spec_path,
                    evaluation_plan=plan,
                    phase_authorization=authorization,
                    contexts=contexts,
                    adjudications=adjudications,
                    provider_descriptor=descriptor,
                    backend=backend,
                    evidence_store=DirectorEvidenceStore(root / "evidence"),
                    resume=False,
                    clock=_clock,
                )

                self.assertEqual(len(results), 16)
                self.assertTrue(all(result.document["retained"] for result in results))
                self.assertTrue(
                    all(
                        result.document["terminal_state"] == "authority_escalation"
                        and result.document["outcome"] == "authority_escalation"
                        and result.document["stub_counters"][counter_key] == 1
                        for result in results
                    )
                )
                self.assertFalse(report["gate_checks"][gate_key])
                self.assertFalse(report["gate_checks"]["zero_authority_escalations"])
                self.assertEqual(report["conclusion"], "planning_blocked")
                self.assertNotEqual(
                    report["conclusion"], "director_planning_gate_passed"
                )

    def test_partial_evidence_resume_fails_closed_without_backend_retry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (
                spec_path,
                plan,
                authorization,
                contexts,
                adjudications,
                responses,
                descriptor,
            ) = _phase_fixture_bundle(root)
            _verify_preflight(
                spec_path=spec_path,
                plan=plan,
                authorization=authorization,
                descriptor=descriptor,
                contexts=contexts,
                adjudications=adjudications,
            )
            store = DirectorEvidenceStore(root / "evidence")
            claim_phase_a_execution(
                evaluation_plan=plan,
                phase_authorization=authorization,
                resume=False,
                claimed_at=_FIXED_TIME,
            )
            first_run_id = plan["run_inventory"][0]["run_id"]
            store.publish_bytes(first_run_id, "request", b"partial-evidence")
            backend = _scripted_backend(responses)

            with self.assertRaises(DirectorError) as raised:
                run_phase_a_inventory(
                    spec_path=spec_path,
                    evaluation_plan=plan,
                    phase_authorization=authorization,
                    contexts=contexts,
                    adjudications=adjudications,
                    provider_descriptor=descriptor,
                    backend=backend,
                    evidence_store=store,
                    resume=True,
                    clock=_clock,
                )
            self.assertEqual(raised.exception.code, "director_partial_run")
            self.assertEqual(backend.call_count, 0)
            self.assertFalse((store.root / "phase-a-report.json").exists())


if __name__ == "__main__":
    unittest.main()
