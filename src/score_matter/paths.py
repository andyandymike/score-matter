from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from .errors import BoundaryError

_PART_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_WINDOWS_RESERVED = {
    "aux",
    "clock$",
    "com1",
    "com2",
    "com3",
    "com4",
    "com5",
    "com6",
    "com7",
    "com8",
    "com9",
    "con",
    "lpt1",
    "lpt2",
    "lpt3",
    "lpt4",
    "lpt5",
    "lpt6",
    "lpt7",
    "lpt8",
    "lpt9",
    "nul",
    "prn",
}


def validate_relative_path(value: str) -> PurePosixPath:
    if not isinstance(value, str) or not value:
        raise BoundaryError("relative path must be a non-empty string", code="unsafe_path")
    if len(value) > 512:
        raise BoundaryError("relative path exceeds 512 characters", code="unsafe_path")
    if "\\" in value or "\x00" in value or ":" in value:
        raise BoundaryError(f"unsafe relative path syntax: {value!r}", code="unsafe_path")
    if value.startswith("/") or value.endswith("/") or "//" in value:
        raise BoundaryError(f"path must be normalized and relative: {value!r}", code="unsafe_path")

    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts:
        raise BoundaryError(f"path must be relative: {value!r}", code="unsafe_path")
    for part in path.parts:
        if part in {".", ".."} or not _PART_PATTERN.fullmatch(part):
            raise BoundaryError(f"unsafe path component: {part!r}", code="unsafe_path")
        if part.endswith((".", " ")):
            raise BoundaryError(f"Windows-unsafe path component: {part!r}", code="unsafe_path")
        if part.split(".", 1)[0].lower() in _WINDOWS_RESERVED:
            raise BoundaryError(f"reserved Windows path component: {part!r}", code="unsafe_path")
    return path


def resolve_inside(root: Path | str, relative: str) -> Path:
    logical = validate_relative_path(relative)
    root_path = Path(root)
    if root_path.exists() and root_path.is_symlink():
        raise BoundaryError(f"store root cannot be a symlink: {root_path}", code="unsafe_store")
    resolved_root = root_path.resolve()
    candidate = resolved_root.joinpath(*logical.parts)

    current = resolved_root
    for part in logical.parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise BoundaryError(f"store path crosses a symlink: {current}", code="unsafe_store")

    resolved_candidate = candidate.resolve(strict=False)
    try:
        resolved_candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise BoundaryError(f"path escapes store root: {relative!r}", code="unsafe_store") from exc
    return candidate


def relative_to_root(path: Path, root: Path) -> str:
    try:
        logical = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise BoundaryError(f"path is outside root: {path}", code="unsafe_store") from exc
    validate_relative_path(logical)
    return logical
