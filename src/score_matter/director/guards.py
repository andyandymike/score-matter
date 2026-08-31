from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from score_matter.canonical import canonical_sha256
from score_matter.errors import DirectorError


@dataclass(frozen=True)
class ForbiddenCall:
    service: str
    method: str
    arguments_sha256: str


@dataclass
class FailIfCalledService:
    """Spy that records forbidden Phase A service access and then stops it."""

    service: str
    calls: list[ForbiddenCall] = field(default_factory=list)

    def invoke(self, method: str, *args: Any, **kwargs: Any) -> None:
        try:
            arguments_sha256 = canonical_sha256(
                {"args": list(args), "kwargs": dict(sorted(kwargs.items()))}
            )
        except Exception:
            # Arguments are never executed or serialized to evidence here.  A
            # stable opaque marker still proves that a forbidden call occurred.
            arguments_sha256 = canonical_sha256({"unserializable": True})
        self.calls.append(
            ForbiddenCall(
                service=self.service,
                method=method,
                arguments_sha256=arguments_sha256,
            )
        )
        raise DirectorError(
            f"Phase A forbids {self.service}.{method}",
            code="forbidden_phase_a_call",
        )

    @property
    def call_count(self) -> int:
        return len(self.calls)


@dataclass
class PhaseAServices:
    """The complete service surface visible to a Phase A backend.

    All three services are fail-if-called.  A normal command backend ignores
    this object; injecting it makes accidental or malicious access testable.
    """

    generator: FailIfCalledService = field(
        default_factory=lambda: FailIfCalledService("generator")
    )
    critic: FailIfCalledService = field(
        default_factory=lambda: FailIfCalledService("critic")
    )
    reference_audio_reader: FailIfCalledService = field(
        default_factory=lambda: FailIfCalledService("reference_audio_reader")
    )

    def counters(self) -> dict[str, int]:
        return {
            "generator_calls": self.generator.call_count,
            "critic_calls": self.critic.call_count,
            "reference_audio_reader_calls": self.reference_audio_reader.call_count,
        }

    def call_evidence(self) -> list[dict[str, str]]:
        calls = (
            self.generator.calls
            + self.critic.calls
            + self.reference_audio_reader.calls
        )
        return [
            {
                "service": call.service,
                "method": call.method,
                "arguments_sha256": call.arguments_sha256,
            }
            for call in calls
        ]
