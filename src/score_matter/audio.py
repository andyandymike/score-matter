"""Optional shared audio entry point; importing it needs no audio dependencies."""
from __future__ import annotations

import json
from typing import Sequence

CORE_VERSION = "0.6.0"


def main(argv: Sequence[str] | None = None) -> int:
    try:
        from matter_audio_core import __version__ as installed_version
    except ModuleNotFoundError as exc:
        if exc.name != "matter_audio_core":
            raise
        error = {"code": "audio_dependency_missing",
                 "message": "Install the optional audio environment using docs/shared-audio.md.",
                 "details": {"required_core_version": CORE_VERSION}}
    else:
        if installed_version == CORE_VERSION:
            from matter_audio_core.cli import run
            from .sa3_edit import registry
            return run(argv, product="score-matter", registry=registry())
        error = {"code": "audio_dependency_incompatible",
                 "message": "Install the pinned audio requirements using docs/shared-audio.md.",
                 "details": {"required_core_version": CORE_VERSION,
                             "installed_core_version": installed_version}}
    print(json.dumps({"schema": "matter-error/v1", "status": "failed", "error": error}))
    return 2
