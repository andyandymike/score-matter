from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from score_matter.canonical import (
    canonical_bytes,
    publish_bytes_no_replace,
    sha256_bytes,
)
from score_matter.errors import BoundaryError
from score_matter.paths import resolve_inside

_RUN_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_ROLES = {
    "request",
    "raw-response",
    "agent-response",
    "gap-report",
    "direction-set",
    "brief-draft",
    "plan-draft",
    "trace",
    "run-result",
}


@dataclass(frozen=True)
class DirectorEvidenceFile:
    path: Path
    sha256: str
    byte_count: int


class DirectorEvidenceStore:
    """Immutable, path-bounded JSON/raw evidence store for director runs."""

    def __init__(self, root: Path | str) -> None:
        candidate = Path(root)
        if candidate.exists():
            if candidate.is_symlink() or not candidate.is_dir():
                raise BoundaryError(f"director evidence root must be a directory: {candidate}")
        else:
            candidate.mkdir(parents=True, exist_ok=False)
        self.root = candidate.resolve()

    def publish_json(
        self, run_id: str, role: str, document: dict[str, Any]
    ) -> DirectorEvidenceFile:
        return self.publish_bytes(run_id, role, canonical_bytes(document))

    def publish_bytes(self, run_id: str, role: str, data: bytes) -> DirectorEvidenceFile:
        if not _RUN_ID.fullmatch(run_id):
            raise BoundaryError(f"invalid director run id: {run_id!r}")
        if role not in _ROLES:
            raise BoundaryError(f"invalid director evidence role: {role!r}")
        if len(data) > 1024 * 1024:
            raise BoundaryError("director evidence file exceeds 1048576 bytes")
        target = resolve_inside(self.root, f"runs/{run_id}/{role}.json")
        publish_bytes_no_replace(target, data)
        return DirectorEvidenceFile(
            path=target,
            sha256=sha256_bytes(data),
            byte_count=len(data),
        )

    def publish_phase_json(
        self, role: str, document: dict[str, Any]
    ) -> DirectorEvidenceFile:
        if role != "phase-a-report":
            raise BoundaryError(f"invalid director phase evidence role: {role!r}")
        data = canonical_bytes(document)
        target = resolve_inside(self.root, f"{role}.json")
        publish_bytes_no_replace(target, data)
        return DirectorEvidenceFile(
            path=target,
            sha256=sha256_bytes(data),
            byte_count=len(data),
        )
