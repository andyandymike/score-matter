from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from score_matter import __version__
from score_matter.canonical import canonical_sha256
from score_matter.contracts import validate_document
from score_matter.errors import IntegrityError
from score_matter.media import probe_pcm_wav
from score_matter.store import ArtifactStore, StoredFile

from .base import ExecutionContext, environment_record, format_timestamp


def create_artifact_evidence(
    *,
    store: ArtifactStore,
    source_path: Path,
    provenance: str,
    media: dict[str, Any] | None = None,
) -> tuple[StoredFile, StoredFile, dict[str, Any]]:
    artifact = store.publish_file(source_path)
    media_record = probe_pcm_wav(artifact.absolute_path)
    if media is not None and media_record != media:
        raise IntegrityError("stored artifact WAV facts changed between probe and publication")
    hex_digest = artifact.sha256.removeprefix("sha256:")
    manifest = {
        "schema": "score-artifact-manifest/v1",
        "artifact_id": f"artifact.{hex_digest[:24]}",
        "role": "raw",
        "provenance": provenance,
        "sha256": artifact.sha256,
        "byte_count": artifact.byte_count,
        "store_path": artifact.relative_path,
        "media": media_record,
        "parent_artifact_sha256": [],
        "transforms": [],
        "authority_class": "candidate",
    }
    validate_document(manifest, expected_schema="score-artifact-manifest/v1")
    manifest_file = store.publish_manifest(manifest)
    return artifact, manifest_file, manifest


def build_run_receipt(
    *,
    context: ExecutionContext,
    execution_id: str,
    operation: str,
    request_sha256: str,
    source_run_receipt_sha256: str | None,
    provider_id: str,
    provider_descriptor_sha256: str,
    started_at: datetime,
    ended_at: datetime,
    requested_seed: int | None,
    effective_seed: int | None,
    artifacts: list[tuple[StoredFile, StoredFile]],
    warnings: list[str],
    reproducibility: str,
    bit_exact_regeneration_guaranteed: bool,
) -> dict[str, Any]:
    elapsed_ms = max(0, int((ended_at - started_at).total_seconds() * 1000))
    document = {
        "schema": "score-run-receipt/v1",
        "execution_id": execution_id,
        "operation": operation,
        "request_sha256": request_sha256,
        "source_run_receipt_sha256": source_run_receipt_sha256,
        "provider_id": provider_id,
        "provider_descriptor_sha256": provider_descriptor_sha256,
        "adapter_version": __version__,
        "started_at": format_timestamp(started_at),
        "ended_at": format_timestamp(ended_at),
        "elapsed_ms": elapsed_ms,
        "requested_seed": requested_seed,
        "effective_seed": effective_seed,
        "environment": environment_record(),
        "isolation": {
            "profile": "process_observed",
            "network": "not_used_by_builtin",
        },
        "warnings": warnings,
        "artifacts": [
            {
                "artifact_sha256": artifact.sha256,
                "byte_count": artifact.byte_count,
                "store_path": artifact.relative_path,
                "manifest_sha256": manifest.sha256,
                "manifest_path": manifest.relative_path,
            }
            for artifact, manifest in artifacts
        ],
        "reproducibility": reproducibility,
        "bit_exact_regeneration_guaranteed": bit_exact_regeneration_guaranteed,
    }
    validate_document(document, expected_schema="score-run-receipt/v1")
    return document


def descriptor_digest(descriptor: dict[str, Any]) -> str:
    validate_document(descriptor, expected_schema="score-provider-descriptor/v1")
    return canonical_sha256(descriptor)
