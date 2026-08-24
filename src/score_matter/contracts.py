from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from .canonical import canonical_sha256, load_json_bytes, load_json_file
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
