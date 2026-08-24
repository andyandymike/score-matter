from __future__ import annotations

from pathlib import Path
from typing import Any

from score_matter.canonical import canonical_sha256
from score_matter.contracts import load_contract
from score_matter.errors import IntegrityError
from score_matter.media import probe_pcm_wav
from score_matter.store import ArtifactStore, StoredFile

from .base import ExecutionContext, builtin_descriptor
from .common import build_run_receipt, descriptor_digest

provider_id = "replay"


def descriptor() -> dict[str, Any]:
    return builtin_descriptor(
        provider_id=provider_id,
        execution_mode="replay",
        module_path=Path(__file__),
        capabilities=[
            {
                "capability_id": "artifact_replay",
                "state": "verified",
                "constraints": {"regenerates_audio": False},
                "evidence": "project-authored M0 integrity tests",
            },
            {
                "capability_id": "text_to_music",
                "state": "unsupported",
                "constraints": {},
                "evidence": "replay verifies bytes and invokes no model",
            },
        ],
    )


def verify(
    source_receipt_path: Path | str,
    context: ExecutionContext,
) -> tuple[StoredFile, dict[str, Any]]:
    started_at = context.clock()
    source_receipt = load_contract(
        source_receipt_path, expected_schema="score-run-receipt/v1"
    )
    if source_receipt["operation"] == "replay":
        raise IntegrityError("replay must bind the original generate/ingest receipt")
    if source_receipt["source_run_receipt_sha256"] is not None:
        raise IntegrityError("source generate/ingest receipt unexpectedly references another run")

    source_digest = canonical_sha256(source_receipt)
    artifacts: list[tuple[StoredFile, StoredFile]] = []
    for entry in source_receipt["artifacts"]:
        artifact_path = context.store.verify_file(
            entry["store_path"], entry["artifact_sha256"], entry["byte_count"]
        )
        stored_manifest = context.store.verify_digest(
            entry["manifest_path"], entry["manifest_sha256"]
        )
        manifest_path = stored_manifest.absolute_path
        manifest = load_contract(
            manifest_path, expected_schema="score-artifact-manifest/v1"
        )
        if manifest["sha256"] != entry["artifact_sha256"]:
            raise IntegrityError("artifact manifest digest does not match run receipt")
        if manifest["byte_count"] != entry["byte_count"]:
            raise IntegrityError("artifact manifest byte count does not match run receipt")
        if manifest["store_path"] != entry["store_path"]:
            raise IntegrityError("artifact manifest path does not match run receipt")
        if probe_pcm_wav(artifact_path) != manifest["media"]:
            raise IntegrityError("artifact decoded WAV facts do not match manifest")
        artifacts.append(
            (
                StoredFile(
                    entry["artifact_sha256"],
                    entry["byte_count"],
                    entry["store_path"],
                    artifact_path,
                ),
                stored_manifest,
            )
        )

    execution_id = context.execution_id_factory()
    ended_at = context.clock()
    replay_descriptor = descriptor()
    receipt = build_run_receipt(
        context=context,
        execution_id=execution_id,
        operation="replay",
        request_sha256=source_receipt["request_sha256"],
        source_run_receipt_sha256=source_digest,
        provider_id=provider_id,
        provider_descriptor_sha256=descriptor_digest(replay_descriptor),
        started_at=started_at,
        ended_at=ended_at,
        requested_seed=source_receipt["requested_seed"],
        effective_seed=source_receipt["effective_seed"],
        artifacts=artifacts,
        warnings=["verification_only_no_audio_regeneration"],
        reproducibility="exact",
        bit_exact_regeneration_guaranteed=False,
    )
    receipt_file = context.store.publish_run_receipt(receipt)
    return receipt_file, receipt
