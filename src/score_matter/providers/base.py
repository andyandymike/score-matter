from __future__ import annotations

import platform
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from score_matter import __version__
from score_matter.canonical import file_sha256
from score_matter.contracts import validate_document
from score_matter.store import ArtifactStore

Clock = Callable[[], datetime]
ExecutionIdFactory = Callable[[], str]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_execution_id() -> str:
    return f"run.{uuid.uuid4().hex}"


def format_timestamp(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    if normalized.microsecond:
        return normalized.isoformat(timespec="microseconds").replace("+00:00", "Z")
    return normalized.isoformat(timespec="seconds").replace("+00:00", "Z")


def environment_record() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "platform": platform.system().lower() or "unknown",
        "machine": platform.machine().lower() or "unknown",
    }


@dataclass
class ExecutionContext:
    store: ArtifactStore
    clock: Clock = utc_now
    execution_id_factory: ExecutionIdFactory = default_execution_id


class Provider(Protocol):
    provider_id: str

    def descriptor(self) -> dict[str, Any]: ...


def builtin_descriptor(
    *,
    provider_id: str,
    execution_mode: str,
    module_path: Path,
    capabilities: list[dict[str, Any]],
    max_input_bytes: int = 64 * 1024 * 1024,
    max_duration_samples: int = 230400000,
) -> dict[str, Any]:
    document = {
        "schema": "score-provider-descriptor/v1",
        "provider_id": provider_id,
        "adapter_version": __version__,
        "execution_mode": execution_mode,
        "protocol_version": "score-provider-protocol/v1",
        "components": [
            {
                "component_id": f"score-matter.{provider_id}.adapter",
                "kind": "adapter",
                "locator": f"builtin://score_matter.providers.{provider_id}",
                "revision": __version__,
                "sha256": file_sha256(module_path),
                "license_snapshot_id": "score-matter.project-mit.2026-08-24",
            }
        ],
        "capabilities": capabilities,
        "limits": {
            "max_input_bytes": max_input_bytes,
            "max_duration_samples": max_duration_samples,
            "formats": ["wav_pcm_s16le"],
        },
    }
    return validate_document(document, expected_schema="score-provider-descriptor/v1")
