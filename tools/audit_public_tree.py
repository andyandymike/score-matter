from __future__ import annotations

import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable

MAX_PUBLIC_FILE_BYTES = 5 * 1024 * 1024
MAX_AUDIO_FIXTURE_BYTES = 1 * 1024 * 1024

_DENIED_PREFIXES = (
    ".local/",
    "artifacts/",
    "benchmark-results/",
    "build/",
    "dist/",
    "downloads/",
    "model-cache/",
    "models/",
    "planning-private/",
    "renders/",
    "spec/",
    "weights/",
)
_MODEL_SUFFIXES = {".ckpt", ".gguf", ".onnx", ".pt", ".pth", ".safetensors"}
_AUDIO_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
_GENERATED_SUFFIXES = {".log", ".pyc"}
_SECRET_SUFFIXES = {".key", ".pem"}
_SECRET_BASENAMES = {
    ".pypirc",
    "id_dsa",
    "id_ed25519",
    "id_rsa",
    "credentials.json",
    "service-account.json",
}
_FORBIDDEN_TEXT_MARKERS = (
    b"-----BEGIN " + b"OPENSSH PRIVATE KEY-----",
    b"-----BEGIN " + b"PRIVATE KEY-----",
)
_AUDIO_FIXTURE_PREFIX = "tests/fixtures/audio/"
_AUDIO_RIGHTS_RECORD = "tests/fixtures/audio/ASSET_RIGHTS.json"


def _git_paths(repo: Path, *arguments: str) -> set[PurePosixPath]:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z", *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return {
        PurePosixPath(item.decode("utf-8", errors="strict"))
        for item in result.stdout.split(b"\0")
        if item
    }


def candidate_paths(repo: Path) -> list[PurePosixPath]:
    tracked = _git_paths(repo)
    untracked = _git_paths(repo, "--others", "--exclude-standard")
    return sorted(tracked | untracked, key=lambda path: path.as_posix())


def audit_paths(repo: Path, paths: Iterable[PurePosixPath]) -> list[str]:
    repo = repo.resolve()
    normalized_paths = sorted(set(paths), key=lambda path: path.as_posix())
    problems: list[str] = []
    casefolded: dict[str, str] = {}
    audio_fixtures: list[str] = []

    logical_names = {path.as_posix() for path in normalized_paths}
    for relative in normalized_paths:
        logical = relative.as_posix()
        lower = logical.lower()
        folded = logical.casefold()
        previous = casefolded.setdefault(folded, logical)
        if previous != logical:
            problems.append(f"case-colliding paths: {previous!r} and {logical!r}")

        if logical.startswith("/") or ".." in relative.parts or "\\" in logical:
            problems.append(f"unsafe repository path: {logical}")
            continue
        if any(lower == prefix[:-1] or lower.startswith(prefix) for prefix in _DENIED_PREFIXES):
            problems.append(f"private/generated path must not be public: {logical}")

        basename = relative.name.lower()
        if basename == ".env" or (basename.startswith(".env.") and basename != ".env.example"):
            problems.append(f"environment secret file must not be public: {logical}")
        if basename in _SECRET_BASENAMES:
            problems.append(f"secret-bearing filename must not be public: {logical}")

        suffix = relative.suffix.lower()
        if suffix in _SECRET_SUFFIXES:
            problems.append(f"secret-bearing file suffix must not be public: {logical}")
        if suffix in _MODEL_SUFFIXES:
            problems.append(f"model/weight binary must not be public: {logical}")
        if suffix in _GENERATED_SUFFIXES:
            problems.append(f"generated file must not be public: {logical}")
        if suffix in _AUDIO_SUFFIXES:
            if not lower.startswith(_AUDIO_FIXTURE_PREFIX):
                problems.append(f"audio must stay local or in the bounded fixture lane: {logical}")
            else:
                audio_fixtures.append(logical)

        absolute = repo.joinpath(*relative.parts)
        if not absolute.exists():
            problems.append(f"candidate path is missing from the worktree: {logical}")
            continue
        if absolute.is_symlink() or not absolute.is_file():
            problems.append(f"public tree entry must be a regular non-symlink file: {logical}")
            continue
        size = absolute.stat().st_size
        if size > MAX_PUBLIC_FILE_BYTES:
            problems.append(f"public file exceeds {MAX_PUBLIC_FILE_BYTES} bytes: {logical}")
        if suffix in _AUDIO_SUFFIXES and size > MAX_AUDIO_FIXTURE_BYTES:
            problems.append(f"audio fixture exceeds {MAX_AUDIO_FIXTURE_BYTES} bytes: {logical}")
        if size <= MAX_PUBLIC_FILE_BYTES:
            data = absolute.read_bytes()
            for marker in _FORBIDDEN_TEXT_MARKERS:
                if marker in data:
                    problems.append(f"private-key marker found in public file: {logical}")
                    break

    if audio_fixtures and _AUDIO_RIGHTS_RECORD not in logical_names:
        problems.append(
            f"audio fixtures require the public rights record: {_AUDIO_RIGHTS_RECORD}"
        )
    return sorted(set(problems))


def main() -> int:
    repo = Path(__file__).resolve().parents[1]
    try:
        paths = candidate_paths(repo)
        problems = audit_paths(repo, paths)
    except (OSError, subprocess.CalledProcessError, UnicodeError) as exc:
        print(f"SCORE_PUBLIC_TREE_ERROR audit_failed={exc}", file=sys.stderr)
        return 2
    if problems:
        for problem in problems:
            print(f"SCORE_PUBLIC_TREE_ERROR {problem}", file=sys.stderr)
        return 1
    print(f"SCORE_PUBLIC_TREE_OK files={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
