from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from score_matter.canonical import canonical_bytes, load_json_file
from score_matter.contracts import validate_document
from score_matter.director.evidence import DirectorEvidenceStore
from score_matter.director.host import (
    build_host_agent_request,
    build_host_agent_submission,
    ingest_host_agent_submission,
)
from score_matter.errors import ContractError

from tests.test_director_compiler import (
    _provider_descriptor,
    _ready_adjudication,
    _ready_context,
    _ready_response,
)


_FIXED_TIME = datetime(2026, 8, 31, tzinfo=timezone.utc)


def _valid_receipt_and_claim(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    descriptor = _provider_descriptor()
    context = _ready_context(descriptor)
    claim_path = root / "claims" / "host-p01.json"
    request = build_host_agent_request(
        run_id="host-p01",
        context=context,
        provider_descriptor=descriptor,
        evidence_root=root / "evidence",
        ingest_claim_path=claim_path,
    )
    submission = build_host_agent_submission(
        request=request,
        raw_response=canonical_bytes(_ready_response(context)),
        submission_id="host-p01-submission",
        host_product="codex",
        captured_at=_FIXED_TIME,
    )
    evidence = ingest_host_agent_submission(
        request=request,
        raw_submission=canonical_bytes(submission),
        evidence_store=DirectorEvidenceStore(root / "evidence"),
        adjudication=_ready_adjudication(context),
        reported_at=_FIXED_TIME,
    )
    return evidence.document, load_json_file(claim_path)


class DirectorHostContractConsistencyTests(unittest.TestCase):
    def test_receipt_rejects_conclusion_and_hash_chain_contradictions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            receipt, _claim = _valid_receipt_and_claim(Path(temporary))

        validate_document(
            receipt, expected_schema="score-director-host-ingest-receipt/v1"
        )
        mutations: list[dict[str, Any]] = []

        semantic_mismatch = copy.deepcopy(receipt)
        semantic_mismatch["validation"]["semantic_valid"] = False
        mutations.append(semantic_mismatch)

        wrong_conclusion = copy.deepcopy(receipt)
        wrong_conclusion["conclusion"] = "diagnostic_contract_validated"
        mutations.append(wrong_conclusion)

        success_with_error = copy.deepcopy(receipt)
        success_with_error["validation"]["errors"] = [
            {"code": "unexpected-error", "path": "$", "message": "unexpected"}
        ]
        mutations.append(success_with_error)

        partial_draft_chain = copy.deepcopy(receipt)
        partial_draft_chain["direction_set_sha256"] = None
        mutations.append(partial_draft_chain)

        retained_submission_drift = copy.deepcopy(receipt)
        retained_submission_drift["retained_raw_submission_sha256"] = (
            "sha256:" + "0" * 64
        )
        mutations.append(retained_submission_drift)

        retained_response_drift = copy.deepcopy(receipt)
        retained_response_drift["retained_raw_response_sha256"] = (
            "sha256:" + "0" * 64
        )
        mutations.append(retained_response_drift)

        rejected_without_error = copy.deepcopy(receipt)
        rejected_without_error["conclusion"] = "submission_rejected"
        rejected_without_error["validation"]["semantic_valid"] = None
        rejected_without_error["adjudication_result"] = None
        mutations.append(rejected_without_error)

        rejected_after_complete_without_adjudication = copy.deepcopy(receipt)
        rejected_after_complete_without_adjudication["conclusion"] = (
            "submission_rejected"
        )
        rejected_after_complete_without_adjudication["adjudication_sha256"] = None
        rejected_after_complete_without_adjudication["adjudication_result"] = None
        rejected_after_complete_without_adjudication["validation"][
            "semantic_valid"
        ] = None
        rejected_after_complete_without_adjudication["validation"]["errors"] = [
            {
                "code": "impossible-postcompile-error",
                "path": "$",
                "message": "no adjudication was supplied",
            }
        ]
        mutations.append(rejected_after_complete_without_adjudication)

        for mutation in mutations:
            with self.subTest(conclusion=mutation["conclusion"]):
                with self.assertRaises(ContractError):
                    validate_document(
                        mutation,
                        expected_schema="score-director-host-ingest-receipt/v1",
                    )

    def test_claim_requires_an_absolute_nonroot_evidence_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            _receipt, claim = _valid_receipt_and_claim(Path(temporary))

        validate_document(
            claim, expected_schema="score-director-host-ingest-claim/v1"
        )
        for invalid_root in ("relative/evidence", str(Path(claim["evidence_root"]).anchor)):
            invalid = copy.deepcopy(claim)
            invalid["evidence_root"] = invalid_root
            with self.subTest(evidence_root=invalid_root):
                with self.assertRaises(ContractError):
                    validate_document(
                        invalid,
                        expected_schema="score-director-host-ingest-claim/v1",
                    )

    def test_response_capture_rejects_base64_count_and_digest_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            descriptor = _provider_descriptor()
            context = _ready_context(descriptor)
            request = build_host_agent_request(
                run_id="host-p01",
                context=context,
                provider_descriptor=descriptor,
                evidence_root=root / "evidence",
                ingest_claim_path=root / "claims" / "host-p01.json",
            )
            submission = build_host_agent_submission(
                request=request,
                raw_response=canonical_bytes(_ready_response(context)),
                submission_id="host-p01-submission",
                host_product="codex",
                captured_at=_FIXED_TIME,
            )

        validate_document(
            submission, expected_schema="score-director-host-submission/v1"
        )
        invalid_base64 = copy.deepcopy(submission)
        invalid_base64["response_capture"]["data_base64"] = "A"

        wrong_count = copy.deepcopy(submission)
        wrong_count["response_capture"]["raw_byte_count"] += 1

        wrong_digest = copy.deepcopy(submission)
        wrong_digest["response_capture"]["raw_sha256"] = "sha256:" + "0" * 64

        for mutation in (invalid_base64, wrong_count, wrong_digest):
            with self.assertRaises(ContractError):
                validate_document(
                    mutation,
                    expected_schema="score-director-host-submission/v1",
                )


if __name__ == "__main__":
    unittest.main()
