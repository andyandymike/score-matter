from __future__ import annotations

from pathlib import Path
from typing import Any

from .canonical import canonical_sha256, write_canonical_no_replace
from .contracts import validate_document
from .errors import BoundaryError
from .providers.registry import descriptor_for


def create_demo_bundle(output: Path | str, *, provider_id: str) -> Path:
    if provider_id not in {"mock", "manual"}:
        raise BoundaryError("demo bundle supports only mock or manual providers")
    root = Path(output)
    if root.exists():
        raise BoundaryError(f"demo output already exists: {root}", code="destination_exists")
    root.mkdir(parents=True, exist_ok=False)

    brief = {
        "schema": "score-brief/v1",
        "brief_id": "score-matter.demo.menu-bed",
        "revision": 1,
        "project_id": "score-matter",
        "cue_id": "demo.menu-bed",
        "intended_use": "internal_eval",
        "gameplay": {
            "role": "menu_bed",
            "foreground_occupancy": "low",
            "entry_intent": "immediate",
            "exit_intent": "fade",
            "neighbor_cue_ids": [],
        },
        "music": {
            "instrumental": True,
            "mood": ["restrained"],
            "energy_curve": "steady_low",
            "bpm": {"minimum": 72, "target": 76, "maximum": 80},
            "key_mode": {"key": "d", "mode": "minor"},
            "meter": {"beats": 4, "unit": 4},
            "sections": [{"section_id": "loop", "bars": 1, "intent": "stable fixture"}],
            "instrumentation_prefer": ["soft_synth"],
            "instrumentation_avoid": ["vocals"],
        },
        "technical": {
            "sample_rate_hz": 48000,
            "channels": 2,
            "target_duration_samples": 4800,
            "loop": {"mode": "full_file", "start_sample": 0, "end_sample": 4800},
            "source_format": "wav_pcm_s16le",
            "delivery_format": "wav_pcm_s16le",
            "loudness_profile_id": "score-fixture.none",
        },
        "constraints": [
            {"constraint_id": "instrumental", "enforcement": "required", "value": True}
        ],
        "references": [],
    }
    validate_document(brief)
    brief_digest = canonical_sha256(brief)

    plan = {
        "schema": "score-plan/v1",
        "plan_id": "score-matter.demo.menu-bed.plan",
        "brief_sha256": brief_digest,
        "package_class": "evaluation_only",
        "sections": [{"section_id": "loop", "bars": 1, "intent": "stable fixture"}],
        "controls": [{"control_id": "bpm", "value": 76, "enforcement": "preferred"}],
        "budget": {"candidate_count": 1, "max_attempts": 1, "max_runtime_seconds": 10},
        "profiles": {
            "qa_profile_id": "score-fixture.none",
            "evaluation_profile_id": "score-fixture.none",
        },
        "allowed_postprocess": [],
    }
    validate_document(plan)
    plan_digest = canonical_sha256(plan)

    review = {
        "schema": "score-plan-review/v1",
        "review_id": "score-matter.demo.menu-bed.review",
        "brief_sha256": brief_digest,
        "plan_sha256": plan_digest,
        "reviewer_alias": "score-matter.fixture",
        "decision": "allow",
        "trust_level": "fixture",
        "reviewed_at": "2026-08-24T00:00:00Z",
    }
    validate_document(review)
    review_digest = canonical_sha256(review)

    descriptor = descriptor_for(provider_id)
    descriptor_digest = canonical_sha256(descriptor)
    if provider_id == "mock":
        options: dict[str, Any] = {
            "schema": "score-provider-options/mock/v1",
            "waveform": "sine",
            "frequency_hz": 220,
            "amplitude": 0.2,
        }
    else:
        options = {"schema": "score-provider-options/manual/v1"}

    request = {
        "schema": "score-resolved-request/v1",
        "request_id": f"score-matter.demo.menu-bed.{provider_id}.request",
        "brief_sha256": brief_digest,
        "plan_sha256": plan_digest,
        "plan_review_sha256": review_digest,
        "provider_descriptor_sha256": descriptor_digest,
        "provider_id": provider_id,
        "candidate_index": 0,
        "requested_seed": 7,
        "output": {
            "format": "wav_pcm_s16le",
            "sample_rate_hz": 48000,
            "channels": 2,
            "duration_samples": 4800,
        },
        "controls": [
            {
                "control_id": "bpm",
                "value": 76,
                "enforcement": "preferred",
                "mapping": "unsupported",
                "verification_plan": "none",
            }
        ],
        "provider_options": options,
    }
    validate_document(request)

    documents = {
        "brief.json": brief,
        "plan.json": plan,
        "plan-review.json": review,
        "resolved-request.json": request,
    }
    try:
        for filename, document in documents.items():
            write_canonical_no_replace(root / filename, document)
    except Exception:
        # The directory did not exist before this command, so cleanup is bounded
        # to the exact newly created demo path.
        for path in root.iterdir():
            path.unlink(missing_ok=True)
        root.rmdir()
        raise
    return root.resolve()
