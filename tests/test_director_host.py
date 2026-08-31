from __future__ import annotations

import base64
import copy
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from score_matter.canonical import (
    canonical_bytes,
    load_json_file,
    sha256_bytes,
    write_canonical_no_replace,
)
from score_matter.cli import HOST_SUBMISSION_READ_MAX_BYTES, main
from score_matter.director.evidence import DirectorEvidenceStore
from score_matter.director.host import (
    build_host_agent_request,
    build_host_agent_submission,
    ingest_host_agent_submission,
)
from score_matter.errors import DirectorError

from tests.test_director_compiler import (
    _provider_descriptor,
    _ready_adjudication,
    _ready_context,
    _ready_response,
)


_FIXED_TIME = datetime(2026, 8, 31, 0, 0, 0, tzinfo=timezone.utc)


def _host_fixture(root: Path) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    descriptor = _provider_descriptor()
    context = _ready_context(descriptor)
    request = build_host_agent_request(
        run_id="host-p01",
        context=context,
        provider_descriptor=descriptor,
        evidence_root=root / "evidence",
        ingest_claim_path=root / "claims" / "host-p01.json",
    )
    adjudication = _ready_adjudication(context)
    return request, context, descriptor, adjudication


def _submission(
    request: dict[str, Any],
    response: dict[str, Any],
) -> dict[str, Any]:
    return build_host_agent_submission(
        request=request,
        raw_response=canonical_bytes(response),
        submission_id="host-p01-submission",
        host_product="codex",
        captured_at=_FIXED_TIME,
    )


def _error_codes(receipt: dict[str, Any]) -> set[str]:
    return {item["code"] for item in receipt["validation"]["errors"]}


class DirectorHostIngestTests(unittest.TestCase):
    def test_host_request_rejects_filesystem_root_as_evidence_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            descriptor = _provider_descriptor()
            context = _ready_context(descriptor)
            with self.assertRaises(DirectorError) as raised:
                build_host_agent_request(
                    run_id="host-root-rejected",
                    context=context,
                    provider_descriptor=descriptor,
                    evidence_root=Path(root.anchor),
                    ingest_claim_path=root / "claims" / "host-root-rejected.json",
                )

        self.assertEqual(raised.exception.code, "director_host_path_invalid")

    def test_submission_helper_wraps_bare_response_without_inventing_observations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, context, _descriptor, _adjudication = _host_fixture(root)
            bare_response = _ready_response(context)
            raw_response = canonical_bytes(bare_response)
            submission = build_host_agent_submission(
                request=request,
                raw_response=raw_response,
                submission_id="host-p01-captured",
                host_product="codex",
                captured_at=_FIXED_TIME,
            )

        self.assertEqual(submission["run_id"], request["run_id"])
        self.assertEqual(
            submission["request_sha256"], sha256_bytes(canonical_bytes(request))
        )
        self.assertEqual(
            base64.b64decode(submission["response_capture"]["data_base64"]),
            raw_response,
        )
        self.assertEqual(
            submission["response_capture"]["raw_sha256"],
            sha256_bytes(raw_response),
        )
        self.assertEqual(
            submission["response_capture"]["raw_byte_count"], len(raw_response)
        )
        self.assertEqual(
            submission["usage"],
            {
                "input_tokens": None,
                "output_tokens": None,
                "external_cost_usd": None,
                "elapsed_ms": None,
            },
        )
        self.assertEqual(submission["observed_tool_calls"], [])
        self.assertEqual(
            submission["host_disclosure"]["complete_context_observation"],
            "unavailable",
        )
        self.assertEqual(
            submission["host_disclosure"]["hidden_adjudication_isolation"],
            "not_verified",
        )
        self.assertEqual(
            submission["host_disclosure"]["single_inference"], "not_verified"
        )

    def test_ready_submission_compiles_and_matches_hidden_adjudication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, context, _descriptor, adjudication = _host_fixture(root)
            response = _ready_response(context)
            raw_response = canonical_bytes(response)
            submission = _submission(request, response)
            raw_submission = canonical_bytes(submission)
            store = DirectorEvidenceStore(request["evidence_root"])
            evidence = ingest_host_agent_submission(
                request=request,
                raw_submission=raw_submission,
                evidence_store=store,
                adjudication=adjudication,
                reported_at=_FIXED_TIME,
            )

            receipt = evidence.document
            run_root = store.root / "runs" / request["run_id"]
            self.assertEqual(
                (run_root / "host-submission.json").read_bytes(), raw_submission
            )
            self.assertEqual(
                (run_root / "raw-response.json").read_bytes(), raw_response
            )
            for role in (
                "host-submission",
                "agent-response",
                "gap-report",
                "direction-set",
                "brief-draft",
                "plan-draft",
                "host-ingest-receipt",
            ):
                self.assertTrue((run_root / f"{role}.json").is_file())

        self.assertEqual(receipt["conclusion"], "diagnostic_adjudication_matched")
        self.assertTrue(receipt["validation"]["submission_json_valid"])
        self.assertTrue(receipt["validation"]["submission_schema_valid"])
        self.assertTrue(receipt["validation"]["request_binding_matched"])
        self.assertTrue(receipt["validation"]["response_json_valid"])
        self.assertTrue(receipt["validation"]["response_schema_valid"])
        self.assertTrue(receipt["validation"]["semantic_valid"])
        self.assertEqual(receipt["validation"]["errors"], [])
        self.assertEqual(receipt["raw_submission_sha256"], sha256_bytes(raw_submission))
        self.assertEqual(
            receipt["retained_raw_submission_sha256"], sha256_bytes(raw_submission)
        )
        self.assertEqual(receipt["raw_response_sha256"], sha256_bytes(raw_response))
        self.assertEqual(
            receipt["retained_raw_response_sha256"], sha256_bytes(raw_response)
        )
        self.assertEqual(receipt["assurance"]["kernel_model_calls"], 0)
        self.assertFalse(receipt["assurance"]["capability_pass_eligible"])

    def test_cross_output_root_is_rejected_before_claim_or_publication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, context, _descriptor, _adjudication = _host_fixture(root)
            raw_submission = canonical_bytes(
                _submission(request, _ready_response(context))
            )
            wrong_store = DirectorEvidenceStore(root / "other-evidence")

            with self.assertRaises(DirectorError) as raised:
                ingest_host_agent_submission(
                    request=request,
                    raw_submission=raw_submission,
                    evidence_store=wrong_store,
                    reported_at=_FIXED_TIME,
                )

            self.assertEqual(raised.exception.code, "director_evidence_root_mismatch")
            self.assertFalse(Path(request["ingest_claim_path"]).exists())
            self.assertFalse((wrong_store.root / "runs").exists())

    def test_second_ingest_for_same_request_claim_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, context, _descriptor, _adjudication = _host_fixture(root)
            raw_submission = canonical_bytes(
                _submission(request, _ready_response(context))
            )
            store = DirectorEvidenceStore(request["evidence_root"])
            first = ingest_host_agent_submission(
                request=request,
                raw_submission=raw_submission,
                evidence_store=store,
                reported_at=_FIXED_TIME,
            )

            with self.assertRaises(DirectorError) as raised:
                ingest_host_agent_submission(
                    request=request,
                    raw_submission=raw_submission,
                    evidence_store=store,
                    reported_at=_FIXED_TIME,
                )

            self.assertEqual(
                raised.exception.code, "director_host_ingest_already_claimed"
            )
            self.assertTrue(Path(request["ingest_claim_path"]).is_file())
            self.assertTrue(first.file.path.is_file())

    def test_unknown_usage_remains_null_and_cannot_become_assurance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, context, _descriptor, _adjudication = _host_fixture(root)
            submission = _submission(request, _ready_response(context))
            evidence = ingest_host_agent_submission(
                request=request,
                raw_submission=canonical_bytes(submission),
                evidence_store=DirectorEvidenceStore(request["evidence_root"]),
                reported_at=_FIXED_TIME,
            )

        receipt = evidence.document
        self.assertEqual(receipt["conclusion"], "diagnostic_contract_validated")
        self.assertEqual(
            receipt["usage"],
            {
                "input_tokens": None,
                "output_tokens": None,
                "external_cost_usd": None,
                "elapsed_ms": None,
            },
        )
        self.assertEqual(
            receipt["host_disclosure"],
            {
                "identity_observation": "unavailable",
                "settings_observation": "unavailable",
                "usage_observation": "unavailable",
                "tool_observation": "unavailable",
            },
        )
        for field in (
            "complete_model_visible_context_verified",
            "model_identity_verified",
            "model_settings_verified",
            "token_usage_verified",
            "cost_verified",
            "tool_call_completeness_verified",
            "hidden_adjudication_isolation_verified",
            "single_inference_verified",
            "capability_pass_eligible",
        ):
            self.assertFalse(receipt["assurance"][field], field)

    def test_run_or_request_substitution_is_retained_as_rejection(self) -> None:
        for mutation in ("run_id", "request_sha256"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                request, context, _descriptor, _adjudication = _host_fixture(root)
                submission = _submission(request, _ready_response(context))
                if mutation == "run_id":
                    submission["run_id"] = "host-p02"
                else:
                    submission["request_sha256"] = "sha256:" + "0" * 64
                raw_submission = canonical_bytes(submission)
                store = DirectorEvidenceStore(request["evidence_root"])

                evidence = ingest_host_agent_submission(
                    request=request,
                    raw_submission=raw_submission,
                    evidence_store=store,
                    reported_at=_FIXED_TIME,
                )

                receipt = evidence.document
                run_root = store.root / "runs" / request["run_id"]
                self.assertEqual(
                    (run_root / "host-submission.json").read_bytes(), raw_submission
                )
                self.assertFalse((run_root / "raw-response.json").exists())
                self.assertEqual(receipt["conclusion"], "submission_rejected")
                self.assertTrue(receipt["validation"]["submission_schema_valid"])
                self.assertFalse(receipt["validation"]["request_binding_matched"])
                self.assertFalse(receipt["validation"]["response_json_valid"])
                self.assertFalse(receipt["validation"]["response_schema_valid"])
                self.assertIsNone(receipt["raw_response_sha256"])
                self.assertIsNone(receipt["retained_raw_response_sha256"])
                self.assertIn("director_host_binding_mismatch", _error_codes(receipt))
                self.assertFalse(receipt["assurance"]["capability_pass_eligible"])

    def test_nonempty_tool_calls_are_retained_as_forbidden(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, context, _descriptor, _adjudication = _host_fixture(root)
            submission = _submission(request, _ready_response(context))
            submission["host_disclosure"]["tool_observation"] = "host_reported"
            submission["observed_tool_calls"] = ["filesystem.read"]
            evidence = ingest_host_agent_submission(
                request=request,
                raw_submission=canonical_bytes(submission),
                evidence_store=DirectorEvidenceStore(request["evidence_root"]),
                reported_at=_FIXED_TIME,
            )

        receipt = evidence.document
        self.assertEqual(receipt["conclusion"], "submission_rejected")
        self.assertTrue(receipt["validation"]["request_binding_matched"])
        self.assertFalse(receipt["validation"]["response_schema_valid"])
        self.assertIn("director_tool_call_forbidden", _error_codes(receipt))
        self.assertEqual(receipt["host_disclosure"]["tool_observation"], "host_reported")
        self.assertFalse(receipt["assurance"]["tool_call_completeness_verified"])

    def test_malformed_submission_bytes_are_retained_without_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, _context, _descriptor, _adjudication = _host_fixture(root)
            raw_submission = b'{"schema":"score-director-host-submission/v1",'
            store = DirectorEvidenceStore(request["evidence_root"])
            evidence = ingest_host_agent_submission(
                request=request,
                raw_submission=raw_submission,
                evidence_store=store,
                reported_at=_FIXED_TIME,
            )
            run_root = store.root / "runs" / request["run_id"]
            self.assertEqual(
                (run_root / "host-submission.json").read_bytes(), raw_submission
            )
            self.assertFalse((run_root / "raw-response.json").exists())
            self.assertFalse((run_root / "agent-response.json").exists())
            self.assertFalse((run_root / "gap-report.json").exists())

        receipt = evidence.document
        self.assertEqual(receipt["conclusion"], "submission_rejected")
        self.assertFalse(receipt["validation"]["submission_json_valid"])
        self.assertFalse(receipt["validation"]["submission_schema_valid"])
        self.assertFalse(receipt["validation"]["request_binding_matched"])
        self.assertFalse(receipt["validation"]["response_json_valid"])
        self.assertEqual(receipt["raw_submission_sha256"], sha256_bytes(raw_submission))
        self.assertEqual(
            receipt["retained_raw_submission_sha256"], sha256_bytes(raw_submission)
        )
        self.assertIsNone(receipt["raw_response_sha256"])
        self.assertIsNone(receipt["retained_raw_response_sha256"])
        self.assertIsNone(receipt["agent_response_sha256"])
        self.assertIsNone(receipt["gap_report_sha256"])
        self.assertTrue(receipt["validation"]["errors"])

    def test_malformed_bare_response_is_captured_claimed_retained_and_rejected(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, _context, _descriptor, _adjudication = _host_fixture(root)
            raw_response = b'{"schema":"score-director-agent-response/v1",'
            submission = build_host_agent_submission(
                request=request,
                raw_response=raw_response,
                submission_id="host-p01-malformed-response",
                host_product="codex",
                captured_at=_FIXED_TIME,
            )
            raw_submission = canonical_bytes(submission)
            self.assertEqual(
                base64.b64decode(submission["response_capture"]["data_base64"]),
                raw_response,
            )

            store = DirectorEvidenceStore(request["evidence_root"])
            evidence = ingest_host_agent_submission(
                request=request,
                raw_submission=raw_submission,
                evidence_store=store,
                reported_at=_FIXED_TIME,
            )
            receipt = evidence.document
            run_root = store.root / "runs" / request["run_id"]
            self.assertEqual(
                (run_root / "host-submission.json").read_bytes(), raw_submission
            )
            self.assertEqual(
                (run_root / "raw-response.json").read_bytes(), raw_response
            )
            self.assertTrue(Path(request["ingest_claim_path"]).is_file())
            self.assertFalse((run_root / "agent-response.json").exists())
            self.assertFalse((run_root / "gap-report.json").exists())

        self.assertEqual(receipt["conclusion"], "submission_rejected")
        self.assertTrue(receipt["validation"]["submission_json_valid"])
        self.assertTrue(receipt["validation"]["submission_schema_valid"])
        self.assertTrue(receipt["validation"]["request_binding_matched"])
        self.assertFalse(receipt["validation"]["response_json_valid"])
        self.assertFalse(receipt["validation"]["response_schema_valid"])
        self.assertEqual(receipt["raw_submission_sha256"], sha256_bytes(raw_submission))
        self.assertEqual(
            receipt["retained_raw_submission_sha256"], sha256_bytes(raw_submission)
        )
        self.assertEqual(receipt["raw_response_sha256"], sha256_bytes(raw_response))
        self.assertEqual(
            receipt["retained_raw_response_sha256"], sha256_bytes(raw_response)
        )
        self.assertIsNone(receipt["agent_response_sha256"])
        self.assertIsNone(receipt["gap_report_sha256"])
        self.assertTrue(receipt["validation"]["errors"])

    def test_authority_bearing_response_is_retained_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, context, _descriptor, _adjudication = _host_fixture(root)
            response = copy.deepcopy(_ready_response(context))
            response["direction_payload"]["recommendation_basis"] = (
                "This direction is approved and release-ready."
            )
            submission = _submission(request, response)
            store = DirectorEvidenceStore(request["evidence_root"])
            evidence = ingest_host_agent_submission(
                request=request,
                raw_submission=canonical_bytes(submission),
                evidence_store=store,
                reported_at=_FIXED_TIME,
            )
            run_root = store.root / "runs" / request["run_id"]
            self.assertTrue((run_root / "agent-response.json").is_file())
            self.assertFalse((run_root / "gap-report.json").exists())

        receipt = evidence.document
        self.assertEqual(receipt["conclusion"], "submission_rejected")
        self.assertTrue(receipt["validation"]["request_binding_matched"])
        self.assertFalse(receipt["validation"]["response_schema_valid"])
        self.assertIn("director_authority_escalation", _error_codes(receipt))
        self.assertIsNotNone(receipt["agent_response_sha256"])
        self.assertIsNone(receipt["gap_report_sha256"])
        self.assertFalse(receipt["assurance"]["capability_pass_eligible"])

    def test_cli_rejects_oversize_submission_before_claim_or_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request, _context, _descriptor, _adjudication = _host_fixture(root)
            request_path = root / "host-request.json"
            submission_path = root / "oversize-host-submission.json"
            write_canonical_no_replace(request_path, request)
            with submission_path.open("wb") as writer:
                writer.truncate(HOST_SUBMISSION_READ_MAX_BYTES + 1)

            errors = io.StringIO()
            with redirect_stderr(errors):
                result = main(
                    [
                        "director",
                        "host",
                        "ingest",
                        "--request",
                        str(request_path),
                        "--submission",
                        str(submission_path),
                        "--output",
                        request["evidence_root"],
                    ]
                )

            self.assertEqual(result, 2)
            self.assertIn("SCORE_ERROR code=host_submission_too_large", errors.getvalue())
            self.assertFalse(Path(request["ingest_claim_path"]).exists())
            self.assertFalse(Path(request["evidence_root"]).exists())

    def test_cli_request_then_ingest_records_a_diagnostic_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _request, context, descriptor, adjudication = _host_fixture(root)
            context_path = root / "context.json"
            descriptor_path = root / "provider.json"
            adjudication_path = root / "adjudication.json"
            request_path = root / "host-request.json"
            response_path = root / "host-response.json"
            submission_path = root / "host-submission.json"
            evidence_root = root / "host-evidence"
            claim_path = root / "claims" / "host-p01.json"
            write_canonical_no_replace(context_path, context)
            write_canonical_no_replace(descriptor_path, descriptor)
            write_canonical_no_replace(adjudication_path, adjudication)
            write_canonical_no_replace(response_path, _ready_response(context))

            request_output = io.StringIO()
            with redirect_stdout(request_output):
                request_result = main(
                    [
                        "director",
                        "host",
                        "request",
                        "--run-id",
                        "host-p01",
                        "--context",
                        str(context_path),
                        "--provider-descriptor",
                        str(descriptor_path),
                        "--evidence-root",
                        str(evidence_root),
                        "--claim-path",
                        str(claim_path),
                        "--output",
                        str(request_path),
                    ]
                )
            self.assertEqual(request_result, 0)
            self.assertIn("SCORE_DIRECTOR_HOST_REQUEST_OK", request_output.getvalue())
            self.assertIn("model_calls=0 pass_eligible=false", request_output.getvalue())

            capture_output = io.StringIO()
            with redirect_stdout(capture_output):
                capture_result = main(
                    [
                        "director",
                        "host",
                        "capture",
                        "--request",
                        str(request_path),
                        "--response",
                        str(response_path),
                        "--submission-id",
                        "host-p01-submission",
                        "--host-product",
                        "codex",
                        "--output",
                        str(submission_path),
                    ]
                )
            self.assertEqual(capture_result, 0)
            self.assertIn(
                "SCORE_DIRECTOR_HOST_CAPTURE_OK", capture_output.getvalue()
            )
            self.assertIn(
                "model_calls=0 pass_eligible=false", capture_output.getvalue()
            )

            ingest_output = io.StringIO()
            with redirect_stdout(ingest_output):
                ingest_result = main(
                    [
                        "director",
                        "host",
                        "ingest",
                        "--request",
                        str(request_path),
                        "--submission",
                        str(submission_path),
                        "--adjudication",
                        str(adjudication_path),
                        "--output",
                        str(evidence_root),
                    ]
                )

            receipt_path = (
                evidence_root
                / "runs"
                / "host-p01"
                / "host-ingest-receipt.json"
            )
            receipt = load_json_file(receipt_path)
            cli_request = load_json_file(request_path)
            claim_was_created = claim_path.is_file()

        self.assertEqual(ingest_result, 0)
        self.assertIn(
            "SCORE_DIRECTOR_HOST_RESPONSE_RECORDED",
            ingest_output.getvalue(),
        )
        self.assertIn(
            "conclusion=diagnostic_adjudication_matched",
            ingest_output.getvalue(),
        )
        self.assertIn("model_calls=0 pass_eligible=false", ingest_output.getvalue())
        self.assertEqual(cli_request["evidence_root"], str(evidence_root.resolve()))
        self.assertEqual(cli_request["ingest_claim_path"], str(claim_path.resolve()))
        self.assertTrue(claim_was_created)
        self.assertEqual(receipt["conclusion"], "diagnostic_adjudication_matched")
        self.assertFalse(receipt["assurance"]["capability_pass_eligible"])


if __name__ == "__main__":
    unittest.main()
