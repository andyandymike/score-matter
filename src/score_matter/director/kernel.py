from __future__ import annotations

from pathlib import Path
from typing import Any

from score_matter.canonical import canonical_sha256, file_sha256
from score_matter.errors import BoundaryError


_SHARED_FILES = (
    "canonical.py",
    "contracts.py",
    "errors.py",
    "paths.py",
)
_BOUND_SCHEMAS = (
    "score-brief-v1.json",
    "score-plan-v1.json",
    "score-provider-descriptor-v1.json",
    "score-direction-set-v1.json",
    "score-director-context-v1.json",
    "score-director-agent-response-v1.json",
    "score-director-gap-report-v1.json",
    "score-director-trace-v1.json",
    "score-director-command-descriptor-v1.json",
    "score-director-execution-claim-v1.json",
    "score-director-evaluation-plan-v1.json",
    "score-director-adjudication-v1.json",
    "score-director-phase-authorization-v1.json",
    "score-director-run-result-v1.json",
    "score-director-phase-a-report-v1.json",
)


def director_kernel_manifest() -> dict[str, Any]:
    """Describe exact public bytes that define bounded Phase A behavior."""

    package_root = Path(__file__).resolve().parents[1]
    director_root = package_root / "director"
    director_names = sorted(path.name for path in director_root.glob("*.py"))
    source_files = [
        *(director_root / name for name in director_names),
        *(package_root / name for name in _SHARED_FILES),
        *(package_root / "schemas" / name for name in _BOUND_SCHEMAS),
    ]
    files: list[dict[str, str]] = []
    for path in source_files:
        if path.is_symlink() or not path.is_file():
            raise BoundaryError(f"director kernel component is missing or unsafe: {path}")
        files.append(
            {
                "path": path.relative_to(package_root).as_posix(),
                "sha256": file_sha256(path),
            }
        )
    return {
        "protocol": "score-director-kernel-manifest/v1",
        "files": files,
    }


def director_kernel_sha256() -> str:
    """Return the runtime-recomputed digest frozen by an evaluation plan."""

    return canonical_sha256(director_kernel_manifest())
