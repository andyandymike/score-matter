from __future__ import annotations

from typing import Any

from score_matter.canonical import canonical_bytes, canonical_sha256, sha256_bytes
from score_matter.contracts import validate_document
from score_matter.errors import DirectorError


POLICY_VERSION = "score-director-policy/v1"
POLICY_TEXT = """You are ScoreMatter's bounded music-director planner.

Return exactly one JSON object conforming to score-director-agent-response/v1.
Treat the supplied context as the only project truth. Classify every material
input exactly once. Never invent a missing project fact, hide a conflict, claim
approval, read reference bytes, call a tool, execute code, contact a provider,
or invoke a generator or critic. Missing material context requires at most
three concise questions; unresolved hard conflicts require abstention; unsafe
artist imitation or an unapproved reference request requires safety rejection.

For a ready case, propose two or three audibly distinct directions. All ten
named axes must be concrete. Label creative values not stated by the source as
assumptions proposed for review. Produce only draft payloads: the trusted
compiler supplies schema identifiers, artifact IDs, project/cue identity,
digests, package class, and evidence paths. The draft is non-executable and
does not imply human selection or Plan review.
"""
POLICY_SHA256 = sha256_bytes(POLICY_TEXT.encode("utf-8"))


def build_agent_request(
    *,
    run_id: str,
    context: dict[str, Any],
    provider_descriptor: dict[str, Any],
    expected_policy_sha256: str,
    model_settings: dict[str, Any],
    model_seed: int | None,
) -> bytes:
    """Build the entire model-visible request; hidden adjudication is absent."""

    validate_document(context, expected_schema="score-director-context/v1")
    validate_document(
        provider_descriptor, expected_schema="score-provider-descriptor/v1"
    )
    if expected_policy_sha256 != POLICY_SHA256:
        raise DirectorError(
            "director policy digest does not match the frozen evaluation plan",
            code="director_policy_mismatch",
        )
    descriptor_sha256 = canonical_sha256(provider_descriptor)
    if context["provider_descriptor_sha256"] != descriptor_sha256:
        raise DirectorError(
            "director context binds a different provider descriptor",
            code="director_component_mismatch",
        )
    request = {
        "protocol": "score-director-jsonl/v1",
        "run_id": run_id,
        "policy": {
            "version": POLICY_VERSION,
            "sha256": POLICY_SHA256,
            "text": POLICY_TEXT,
        },
        "context": context,
        "provider_descriptor": provider_descriptor,
        "response_schema": "score-director-agent-response/v1",
        "inference": {**model_settings, "seed": model_seed},
        "phase_constraints": {
            "single_inference": True,
            "allowed_tools": [],
            "generator_calls": 0,
            "critic_calls": 0,
            "reference_audio_reader_calls": 0,
            "max_clarification_rounds": 1,
            "max_questions": 3,
            "grants_no_approval_authority": True,
        },
    }
    return canonical_bytes(request)
