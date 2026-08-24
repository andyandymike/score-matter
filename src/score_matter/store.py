from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import (
    canonical_bytes,
    file_sha256,
    publish_bytes_no_replace,
    sha256_bytes,
    write_canonical_no_replace,
)
from .contracts import validate_document
from .errors import BoundaryError, IntegrityError
from .paths import relative_to_root, resolve_inside


@dataclass(frozen=True)
class StoredFile:
    sha256: str
    byte_count: int
    relative_path: str
    absolute_path: Path


class ArtifactStore:
    def __init__(self, root: Path | str) -> None:
        candidate = Path(root)
        if candidate.exists() and candidate.is_symlink():
            raise BoundaryError(f"artifact store cannot be a symlink: {candidate}")
        candidate.mkdir(parents=True, exist_ok=True)
        self.root = candidate.resolve()

    def _content_relative(self, digest: str, filename: str) -> str:
        hex_digest = digest.removeprefix("sha256:")
        return f"artifacts/sha256/{hex_digest[:2]}/{hex_digest[2:]}/{filename}"

    def publish_file(self, source: Path | str, *, filename: str = "payload.wav") -> StoredFile:
        source_path = Path(source)
        if source_path.is_symlink():
            raise BoundaryError(f"source artifact cannot be a symlink: {source_path}")
        digest = file_sha256(source_path)
        byte_count = source_path.stat().st_size
        relative = self._content_relative(digest, filename)
        target = resolve_inside(self.root, relative)
        target.parent.mkdir(parents=True, exist_ok=True)

        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with source_path.open("rb") as reader, temporary.open("xb") as writer:
                shutil.copyfileobj(reader, writer, length=1024 * 1024)
                writer.flush()
                os.fsync(writer.fileno())
            if file_sha256(temporary) != digest or temporary.stat().st_size != byte_count:
                raise IntegrityError("staged artifact bytes changed during copy")
            try:
                os.link(temporary, target)
            except FileExistsError:
                self.verify_file(relative, digest, byte_count)
            except OSError as exc:
                try:
                    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                except FileExistsError:
                    self.verify_file(relative, digest, byte_count)
                else:
                    with temporary.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
                        shutil.copyfileobj(reader, writer, length=1024 * 1024)
                        writer.flush()
                        os.fsync(writer.fileno())
                    self.verify_file(relative, digest, byte_count)
        finally:
            temporary.unlink(missing_ok=True)

        return StoredFile(digest, byte_count, relative, target)

    def publish_manifest(self, document: dict[str, Any]) -> StoredFile:
        validate_document(document, expected_schema="score-artifact-manifest/v1")
        data = canonical_bytes(document)
        digest = sha256_bytes(data)
        hex_digest = digest.removeprefix("sha256:")
        relative = f"manifests/sha256/{hex_digest[:2]}/{hex_digest[2:]}.json"
        target = resolve_inside(self.root, relative)
        publish_bytes_no_replace(target, data)
        return StoredFile(digest, len(data), relative, target)

    def publish_run_receipt(self, document: dict[str, Any]) -> StoredFile:
        validate_document(document, expected_schema="score-run-receipt/v1")
        execution_id = document["execution_id"]
        relative = f"runs/{execution_id}/run-receipt.json"
        target = resolve_inside(self.root, relative)
        try:
            target.parent.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            raise IntegrityError(
                f"immutable run receipt already exists for execution_id={execution_id}"
            ) from exc
        digest = write_canonical_no_replace(target, document)
        return StoredFile(digest, target.stat().st_size, relative, target)

    def verify_file(self, relative: str, expected_sha256: str, expected_bytes: int) -> Path:
        target = resolve_inside(self.root, relative)
        if not target.is_file() or target.is_symlink():
            raise IntegrityError(f"stored artifact is missing or unsafe: {relative}")
        actual_bytes = target.stat().st_size
        if actual_bytes != expected_bytes:
            raise IntegrityError(
                f"stored artifact byte count mismatch for {relative}: "
                f"expected {expected_bytes}, found {actual_bytes}"
            )
        actual_digest = file_sha256(target)
        if actual_digest != expected_sha256:
            raise IntegrityError(
                f"stored artifact digest mismatch for {relative}: "
                f"expected {expected_sha256}, found {actual_digest}"
            )
        return target

    def verify_digest(self, relative: str, expected_sha256: str) -> StoredFile:
        target = resolve_inside(self.root, relative)
        if not target.is_file() or target.is_symlink():
            raise IntegrityError(f"stored file is missing or unsafe: {relative}")
        byte_count = target.stat().st_size
        actual_digest = file_sha256(target)
        if actual_digest != expected_sha256:
            raise IntegrityError(
                f"stored file digest mismatch for {relative}: "
                f"expected {expected_sha256}, found {actual_digest}"
            )
        return StoredFile(actual_digest, byte_count, relative, target)

    def logical_path(self, path: Path) -> str:
        return relative_to_root(path, self.root)
