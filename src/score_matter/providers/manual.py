from __future__ import annotations

from pathlib import Path
from typing import Any

from score_matter.bundle import ExecutionBundle
from score_matter.canonical import file_sha256
from score_matter.contracts import load_contract
from score_matter.errors import ContractError, IntegrityError
from score_matter.media import probe_pcm_wav
from score_matter.store import StoredFile

from .base import ExecutionContext, builtin_descriptor
from .common import build_run_receipt, create_artifact_evidence, descriptor_digest

provider_id = "manual"


def descriptor() -> dict[str, Any]:
    return builtin_descriptor(
        provider_id=provider_id,
        execution_mode="manual",
        module_path=Path(__file__),
        capabilities=[
            {
                "capability_id": "manual_ingest",
                "state": "verified",
                "constraints": {"format": "wav_pcm_s16le", "rights_upgrade": False},
                "evidence": "project-authored M0 ingestion tests",
            },
            {
                "capability_id": "text_to_music",
                "state": "unsupported",
                "constraints": {},
                "evidence": "manual ingest invokes no model",
            },
            {
                "capability_id": "native_loop",
                "state": "unsupported",
                "constraints": {},
                "evidence": "ingestion does not establish loop quality",
            },
        ],
    )


def ingest(
    bundle: ExecutionBundle,
    context: ExecutionContext,
    *,
    audio_path: Path | str,
    source_record_path: Path | str,
) -> tuple[StoredFile, dict[str, Any]]:
    source_record = load_contract(
        source_record_path, expected_schema="score-manual-source/v1"
    )
    if source_record["intended_use"] != bundle.brief["intended_use"]:
        raise ContractError(
            "manual source intended_use does not match the bound Brief",
            code="source_use_mismatch",
        )
    audio = Path(audio_path)
    actual_digest = file_sha256(audio)
    if source_record["audio_sha256"] != actual_digest:
        raise IntegrityError(
            "manual source record does not bind the exact audio bytes: "
            f"expected {source_record['audio_sha256']}, found {actual_digest}"
        )

    output = bundle.request["output"]
    media = probe_pcm_wav(audio, max_bytes=bundle.provider_descriptor["limits"]["max_input_bytes"])
    expected_media = {
        "container": "wav",
        "codec": "pcm_s16le",
        "sample_rate_hz": output["sample_rate_hz"],
        "channels": output["channels"],
        "sample_width_bytes": 2,
        "frame_count": output["duration_samples"],
    }
    if media != expected_media:
        raise ContractError(
            "manual WAV facts do not match resolved output: "
            f"expected {expected_media}, found {media}"
        )

    execution_id = context.execution_id_factory()
    started_at = context.clock()
    artifact, manifest_file, _ = create_artifact_evidence(
        store=context.store,
        source_path=audio,
        provenance="imported",
        media=media,
    )
    if artifact.sha256 != source_record["audio_sha256"]:
        raise IntegrityError("manual audio bytes changed during ingestion")
    ended_at = context.clock()
    receipt = build_run_receipt(
        context=context,
        execution_id=execution_id,
        operation="ingest",
        request_sha256=bundle.request_sha256,
        source_run_receipt_sha256=None,
        provider_id=provider_id,
        provider_descriptor_sha256=descriptor_digest(bundle.provider_descriptor),
        started_at=started_at,
        ended_at=ended_at,
        requested_seed=bundle.request["requested_seed"],
        effective_seed=None,
        artifacts=[(artifact, manifest_file)],
        warnings=[
            "manual_source_rights_not_reviewed",
            "candidate_only_no_approval",
        ],
        reproducibility="exact",
        bit_exact_regeneration_guaranteed=False,
    )
    receipt_file = context.store.publish_run_receipt(receipt)
    return receipt_file, receipt
