from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import canonical_sha256
from .contracts import load_contract, validate_document
from .errors import BoundaryError, ContractError

_BUNDLE_FILES = {
    "brief.json",
    "plan.json",
    "plan-review.json",
    "resolved-request.json",
}

_BUILTIN_OPTIONS_SCHEMAS = {
    "manual": "score-provider-options/manual/v1",
    "mock": "score-provider-options/mock/v1",
}


@dataclass(frozen=True)
class ExecutionBundle:
    root: Path
    brief: dict[str, Any]
    plan: dict[str, Any]
    plan_review: dict[str, Any]
    request: dict[str, Any]
    provider_descriptor: dict[str, Any]

    @property
    def request_sha256(self) -> str:
        return canonical_sha256(self.request)


def load_execution_bundle(
    root: Path | str,
    *,
    expected_provider_id: str,
    provider_descriptor: dict[str, Any],
) -> ExecutionBundle:
    candidate = Path(root)
    if candidate.is_symlink() or not candidate.is_dir():
        raise BoundaryError(f"execution bundle must be a regular directory: {candidate}")
    resolved_root = candidate.resolve()
    actual_files: set[str] = set()
    for entry in resolved_root.iterdir():
        if entry.is_symlink() or not entry.is_file():
            raise BoundaryError(f"execution bundle contains a non-regular entry: {entry.name}")
        actual_files.add(entry.name)
    if actual_files != _BUNDLE_FILES:
        missing = sorted(_BUNDLE_FILES - actual_files)
        extra = sorted(actual_files - _BUNDLE_FILES)
        raise BoundaryError(
            f"execution bundle inventory mismatch: missing={missing}, extra={extra}"
        )

    brief = load_contract(resolved_root / "brief.json", expected_schema="score-brief/v1")
    plan = load_contract(resolved_root / "plan.json", expected_schema="score-plan/v1")
    review = load_contract(
        resolved_root / "plan-review.json", expected_schema="score-plan-review/v1"
    )
    request = load_contract(
        resolved_root / "resolved-request.json", expected_schema="score-resolved-request/v1"
    )
    descriptor = validate_document(
        provider_descriptor, expected_schema="score-provider-descriptor/v1"
    )

    brief_digest = canonical_sha256(brief)
    plan_digest = canonical_sha256(plan)
    review_digest = canonical_sha256(review)
    descriptor_digest = canonical_sha256(descriptor)

    _require_equal("plan.brief_sha256", plan["brief_sha256"], brief_digest)
    _require_equal("review.brief_sha256", review["brief_sha256"], brief_digest)
    _require_equal("review.plan_sha256", review["plan_sha256"], plan_digest)
    if review["decision"] != "allow":
        raise ContractError("provider execution requires plan review decision=allow")

    _require_equal("request.brief_sha256", request["brief_sha256"], brief_digest)
    _require_equal("request.plan_sha256", request["plan_sha256"], plan_digest)
    _require_equal("request.plan_review_sha256", request["plan_review_sha256"], review_digest)
    _require_equal(
        "request.provider_descriptor_sha256",
        request["provider_descriptor_sha256"],
        descriptor_digest,
    )
    _require_equal("request.provider_id", request["provider_id"], expected_provider_id)
    _require_equal("descriptor.provider_id", descriptor["provider_id"], expected_provider_id)
    expected_options_schema = _BUILTIN_OPTIONS_SCHEMAS.get(expected_provider_id)
    if expected_options_schema is not None:
        _require_equal(
            "request.provider_options.schema",
            request["provider_options"].get("schema"),
            expected_options_schema,
        )

    technical = brief["technical"]
    output = request["output"]
    _require_equal("request.output.format", output["format"], technical["source_format"])
    _require_equal(
        "request.output.sample_rate_hz", output["sample_rate_hz"], technical["sample_rate_hz"]
    )
    _require_equal("request.output.channels", output["channels"], technical["channels"])
    _require_equal(
        "request.output.duration_samples",
        output["duration_samples"],
        technical["target_duration_samples"],
    )
    if output["format"] not in descriptor["limits"]["formats"]:
        raise ContractError("resolved output format is outside provider limits")
    if output["duration_samples"] > descriptor["limits"]["max_duration_samples"]:
        raise ContractError("resolved output duration is outside provider limits")

    if request["candidate_index"] >= plan["budget"]["candidate_count"]:
        raise ContractError("request candidate_index is outside the Plan candidate budget")

    plan_controls = {
        item["control_id"]: (item["value"], item["enforcement"])
        for item in plan["controls"]
    }
    request_controls = {
        item["control_id"]: (item["value"], item["enforcement"])
        for item in request["controls"]
    }
    if plan_controls != request_controls:
        raise ContractError("resolved request controls do not exactly match the Plan controls")

    return ExecutionBundle(resolved_root, brief, plan, review, request, descriptor)


def _require_equal(field: str, actual: Any, expected: Any) -> None:
    if actual != expected:
        raise ContractError(f"stale binding for {field}: expected {expected!r}, found {actual!r}")
