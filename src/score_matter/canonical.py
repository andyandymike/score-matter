from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
from typing import Any

import rfc8785

from .errors import ContractError, IntegrityError, ScoreMatterError

MAX_JSON_BYTES = 1024 * 1024


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractError(f"duplicate JSON key: {key}", code="duplicate_json_key")
        result[key] = value
    return result


def _reject_nonfinite(token: str) -> None:
    raise ContractError(f"non-finite JSON number is forbidden: {token}", code="nonfinite_json")


def load_json_bytes(data: bytes, *, source: str = "<bytes>") -> Any:
    if len(data) > MAX_JSON_BYTES:
        raise ContractError(
            f"JSON input exceeds {MAX_JSON_BYTES} bytes: {source}",
            code="json_too_large",
        )
    if data.startswith(b"\xef\xbb\xbf"):
        raise ContractError(f"UTF-8 BOM is forbidden: {source}", code="json_bom_forbidden")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ContractError(f"JSON is not strict UTF-8: {source}: {exc}") from exc
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except ScoreMatterError:
        raise
    except json.JSONDecodeError as exc:
        raise ContractError(
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {source}: {exc.msg}"
        ) from exc


def load_json_file(path: Path | str) -> Any:
    candidate = Path(path)
    try:
        data = candidate.read_bytes()
    except OSError as exc:
        raise ContractError(f"cannot read JSON file: {candidate}: {exc}") from exc
    return load_json_bytes(data, source=str(candidate))


def canonical_bytes(document: Any) -> bytes:
    try:
        return rfc8785.dumps(document)
    except (rfc8785.CanonicalizationError, TypeError, ValueError) as exc:
        raise ContractError(f"document cannot be RFC 8785/JCS canonicalized: {exc}") from exc


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def canonical_sha256(document: Any) -> str:
    return sha256_bytes(canonical_bytes(document))


def file_sha256(path: Path | str, *, chunk_bytes: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    candidate = Path(path)
    try:
        with candidate.open("rb") as handle:
            while True:
                block = handle.read(chunk_bytes)
                if not block:
                    break
                digest.update(block)
    except OSError as exc:
        raise IntegrityError(f"cannot hash file: {candidate}: {exc}") from exc
    return f"sha256:{digest.hexdigest()}"


def publish_bytes_no_replace(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise IntegrityError(f"immutable output cannot be a symlink: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise IntegrityError(f"existing immutable file has different bytes: {path}")
        except OSError as exc:
            # Some Windows/filesystem configurations disallow hard links. O_EXCL
            # preserves no-replace semantics, though an interrupted write may leave
            # a partial target that later verification will reject.
            try:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            except FileExistsError:
                if path.read_bytes() != data:
                    raise IntegrityError(
                        f"existing immutable file has different bytes: {path}"
                    ) from exc
            else:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
    finally:
        temporary.unlink(missing_ok=True)


def write_canonical_no_replace(path: Path, document: Any) -> str:
    data = canonical_bytes(document)
    publish_bytes_no_replace(path, data)
    return sha256_bytes(data)
