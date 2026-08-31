"""Bounded, model-backed music-director evidence kernel.

The director is deliberately separate from audio providers.  It may propose
advisory planning payloads, but it cannot execute a generator, act as a human
reviewer, or grant creative, rights, package, release, or consumer authority.
"""

from .backends import (
    DirectorBackend,
    DirectorCompletion,
    JsonlCommandDirectorBackend,
    ScriptedDirectorBackend,
)
from .guards import PhaseAServices

__all__ = [
    "DirectorBackend",
    "DirectorCompletion",
    "JsonlCommandDirectorBackend",
    "PhaseAServices",
    "ScriptedDirectorBackend",
]
