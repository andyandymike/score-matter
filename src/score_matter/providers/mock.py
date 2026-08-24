from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from score_matter.bundle import ExecutionBundle
from score_matter.media import probe_pcm_wav, render_mock_sine_wav
from score_matter.store import StoredFile

from .base import ExecutionContext, builtin_descriptor
from .common import build_run_receipt, create_artifact_evidence, descriptor_digest

provider_id = "mock"


def descriptor() -> dict[str, Any]:
    return builtin_descriptor(
        provider_id=provider_id,
        execution_mode="mock",
        module_path=Path(__file__),
        capabilities=[
            {
                "capability_id": "synthetic_fixture",
                "state": "verified",
                "constraints": {"format": "wav_pcm_s16le", "waveform": "sine"},
                "evidence": "project-authored deterministic M0 tests",
            },
            {
                "capability_id": "text_to_music",
                "state": "unsupported",
                "constraints": {},
                "evidence": "the mock adapter is not a music model",
            },
            {
                "capability_id": "native_loop",
                "state": "unsupported",
                "constraints": {},
                "evidence": "fixture byte generation is not seamless-loop evidence",
            },
        ],
    )


def execute(
    bundle: ExecutionBundle, context: ExecutionContext
) -> tuple[StoredFile, dict[str, Any]]:
    request = bundle.request
    output = request["output"]
    options = request["provider_options"]
    execution_id = context.execution_id_factory()
    started_at = context.clock()

    staging_root = context.store.root / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mock-", dir=staging_root) as temporary:
        candidate = Path(temporary) / "candidate.wav"
        render_mock_sine_wav(
            candidate,
            sample_rate_hz=output["sample_rate_hz"],
            channels=output["channels"],
            duration_samples=output["duration_samples"],
            frequency_hz=options["frequency_hz"],
            amplitude=options["amplitude"],
            seed=request["requested_seed"],
        )
        media = probe_pcm_wav(candidate)
        artifact, manifest_file, _ = create_artifact_evidence(
            store=context.store,
            source_path=candidate,
            provenance="native_generated",
            media=media,
        )

    warnings = [
        f"preferred_control_unsupported:{control['control_id']}"
        for control in request["controls"]
        if control["enforcement"] == "preferred" and control["mapping"] == "unsupported"
    ]
    warnings.extend(
        [
            "synthetic_fixture_only",
            "candidate_only_no_approval",
            "bit_exact_cross_platform_regeneration_not_guaranteed",
        ]
    )
    ended_at = context.clock()
    receipt = build_run_receipt(
        context=context,
        execution_id=execution_id,
        operation="generate",
        request_sha256=bundle.request_sha256,
        source_run_receipt_sha256=None,
        provider_id=provider_id,
        provider_descriptor_sha256=descriptor_digest(bundle.provider_descriptor),
        started_at=started_at,
        ended_at=ended_at,
        requested_seed=request["requested_seed"],
        effective_seed=request["requested_seed"],
        artifacts=[(artifact, manifest_file)],
        warnings=warnings,
        reproducibility="best_effort",
        bit_exact_regeneration_guaranteed=False,
    )
    receipt_file = context.store.publish_run_receipt(receipt)
    return receipt_file, receipt
