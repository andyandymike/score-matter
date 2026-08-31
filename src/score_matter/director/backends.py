from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Mapping, Protocol

from score_matter.canonical import (
    canonical_bytes,
    canonical_sha256,
    file_sha256,
    load_json_bytes,
)
from score_matter.errors import BoundaryError, DirectorError

from .guards import PhaseAServices


@dataclass(frozen=True)
class DirectorCompletion:
    """Observed result of exactly one bounded local director-model call."""

    raw_exchange: bytes
    agent_response: dict[str, object]
    input_tokens: int
    output_tokens: int
    elapsed_ms: int
    external_cost_microusd: int
    model_id: str
    model_revision: str
    observed_tool_calls: tuple[str, ...] = ()


class DirectorBackend(Protocol):
    backend_id: str

    def complete(
        self,
        request: bytes,
        *,
        services: PhaseAServices,
        timeout_seconds: int,
    ) -> DirectorCompletion: ...


class DirectorBackendFailure(DirectorError):
    """Backend failure that retains any bytes observed before rejection."""

    def __init__(
        self,
        message: str,
        *,
        code: str,
        raw_output: bytes = b"",
        elapsed_ms: int = 0,
        observed_tool_calls: tuple[str, ...] = (),
    ) -> None:
        super().__init__(message, code=code)
        self.raw_output = raw_output
        self.elapsed_ms = elapsed_ms
        self.observed_tool_calls = observed_tool_calls


class ScriptedDirectorBackend:
    """Dependency-free backend for implementation tests only.

    A scripted result can prove orchestration and fail-closed behavior.  It is
    never evidence that a music-director model understands a scenario.
    """

    backend_id = "scripted_fixture"

    def __init__(
        self,
        completion: DirectorCompletion
        | Callable[[bytes, PhaseAServices, int], DirectorCompletion],
    ) -> None:
        self._completion = completion
        self.call_count = 0

    def complete(
        self,
        request: bytes,
        *,
        services: PhaseAServices,
        timeout_seconds: int,
    ) -> DirectorCompletion:
        self.call_count += 1
        if callable(self._completion):
            return self._completion(request, services, timeout_seconds)
        return self._completion


_SAFE_ENV_NAMES = {
    "CUDA_VISIBLE_DEVICES",
    "HF_HOME",
    "HF_HUB_OFFLINE",
    "OLLAMA_MODELS",
    "TRANSFORMERS_OFFLINE",
}
_SECRET_ENV_PATTERN = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", re.I)
_EXCHANGE_KEYS = {
    "protocol",
    "model_id",
    "model_revision",
    "usage",
    "observed_tool_calls",
    "response",
}


class JsonlCommandDirectorBackend:
    """Invoke one exact, operator-frozen local JSONL wrapper without a shell.

    The wrapper receives one canonical request on stdin and must return one JSON
    exchange on stdout.  The implementation strips proxy variables and forces
    common model libraries into offline mode.  This is process observation,
    not an OS firewall claim; a formal experiment must separately freeze its
    isolation evidence.
    """

    backend_id = "local_jsonl_command"

    def __init__(
        self,
        *,
        executable: Path | str,
        executable_sha256: str,
        arguments: tuple[str, ...] = (),
        environment: Mapping[str, str] | None = None,
        working_directory: Path | str,
        max_output_bytes: int = 1024 * 1024,
        component_sha256: str | None = None,
        bound_artifacts: Mapping[str, str] | None = None,
        working_directory_manifest_sha256: str | None = None,
    ) -> None:
        candidate = Path(executable)
        if candidate.is_symlink() or not candidate.is_file():
            raise BoundaryError(
                f"director executable must be a regular non-symlink file: {candidate}"
            )
        actual_sha256 = file_sha256(candidate)
        if actual_sha256 != executable_sha256:
            raise DirectorError(
                "director executable digest does not match the frozen descriptor",
                code="director_component_mismatch",
            )
        cwd = Path(working_directory)
        if cwd.is_symlink() or not cwd.is_dir():
            raise BoundaryError(
                f"director working directory must be a regular directory: {cwd}"
            )
        if max_output_bytes < 1 or max_output_bytes > 1024 * 1024:
            raise BoundaryError("director max_output_bytes must be in [1, 1048576]")
        if any("\x00" in argument for argument in arguments):
            raise BoundaryError("director argument contains NUL")

        provided_environment = dict(environment or {})
        for name, value in provided_environment.items():
            if name not in _SAFE_ENV_NAMES or _SECRET_ENV_PATTERN.search(name):
                raise BoundaryError(f"director environment name is not allowlisted: {name}")
            if "\x00" in value:
                raise BoundaryError(f"director environment value contains NUL: {name}")

        self._executable = candidate.resolve()
        self._executable_sha256 = executable_sha256
        self._arguments = arguments
        self._environment = provided_environment
        self._working_directory = cwd.resolve()
        self._max_output_bytes = max_output_bytes
        self.component_sha256 = component_sha256
        self._bound_artifacts: dict[Path, str] = {}
        for locator, digest in dict(bound_artifacts or {}).items():
            artifact = Path(locator)
            if not artifact.is_absolute() or artifact.is_symlink() or not artifact.is_file():
                raise BoundaryError(
                    f"bound director runtime artifact must be an absolute regular file: {artifact}"
                )
            self._bound_artifacts[artifact.resolve()] = digest
        self._working_directory_manifest_sha256 = working_directory_manifest_sha256
        self.verify_bound_state()

    def verify_bound_state(self) -> None:
        """Recheck every frozen byte surface observable by this adapter."""

        if file_sha256(self._executable) != self._executable_sha256:
            raise DirectorError(
                "director executable changed after backend construction",
                code="director_component_mismatch",
            )
        for path, expected_sha256 in self._bound_artifacts.items():
            if path.is_symlink() or not path.is_file():
                raise DirectorError(
                    f"bound director runtime artifact is missing or unsafe: {path}",
                    code="director_component_mismatch",
                )
            if file_sha256(path) != expected_sha256:
                raise DirectorError(
                    f"bound director runtime artifact changed: {path}",
                    code="director_component_mismatch",
                )
        if self._working_directory_manifest_sha256 is not None:
            actual = directory_manifest_sha256(self._working_directory)
            if actual != self._working_directory_manifest_sha256:
                raise DirectorError(
                    "director working-directory manifest changed",
                    code="director_component_mismatch",
                )

    def verify_descriptor_binding(self, descriptor: Mapping[str, object]) -> None:
        """Prove this concrete adapter configuration matches one frozen descriptor."""

        expected_artifacts = {
            Path(str(item["locator"])).resolve(): str(item["sha256"])
            for item in descriptor["model_artifacts"]  # type: ignore[index]
        }
        expected_environment = {
            str(item["name"]): str(item["value"])
            for item in descriptor["environment"]  # type: ignore[index]
        }
        matches = (
            self.component_sha256 == canonical_sha256(descriptor)
            and self._executable == Path(str(descriptor["executable"])).resolve()
            and self._executable_sha256 == descriptor["executable_sha256"]
            and self._arguments == tuple(descriptor["arguments"])  # type: ignore[arg-type]
            and self._environment == expected_environment
            and self._working_directory
            == Path(str(descriptor["working_directory"])).resolve()
            and self._max_output_bytes == descriptor["max_output_bytes"]
            and self._bound_artifacts == expected_artifacts
            and self._working_directory_manifest_sha256
            == descriptor["working_directory_manifest_sha256"]
        )
        if not matches:
            raise DirectorError(
                "director backend configuration differs from the frozen descriptor",
                code="director_component_mismatch",
            )

    def complete(
        self,
        request: bytes,
        *,
        services: PhaseAServices,
        timeout_seconds: int,
    ) -> DirectorCompletion:
        del services  # A local command receives no service handles or tool surface.
        if timeout_seconds < 1 or timeout_seconds > 120:
            raise BoundaryError("Phase A per-call timeout must be in [1, 120] seconds")
        self.verify_bound_state()

        environment = self._sanitized_environment()
        started = time.monotonic()
        with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
            try:
                process = subprocess.Popen(
                    [str(self._executable), *self._arguments],
                    stdin=subprocess.PIPE,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=self._working_directory,
                    env=environment,
                    shell=False,
                )
                try:
                    process.communicate(
                        input=request + (b"" if request.endswith(b"\n") else b"\n"),
                        timeout=timeout_seconds,
                    )
                except subprocess.TimeoutExpired as exc:
                    process.kill()
                    process.communicate()
                    raw_output, _ = _spooled_output(
                        stdout_file, max_bytes=self._max_output_bytes
                    )
                    raise DirectorBackendFailure(
                        f"director call exceeded {timeout_seconds} seconds",
                        code="director_timeout",
                        raw_output=raw_output,
                        elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                    ) from exc
            except DirectorBackendFailure:
                raise
            except OSError as exc:
                raise DirectorBackendFailure(
                    f"cannot execute frozen director command: {exc}",
                    code="director_command_failed",
                    elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                ) from exc

            elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            stdout, stdout_was_oversize = _spooled_output(
                stdout_file, max_bytes=self._max_output_bytes
            )
            if stdout_was_oversize:
                raise DirectorBackendFailure(
                    "director stdout exceeds the frozen output-byte ceiling",
                    code="director_output_too_large",
                    raw_output=stdout,
                    elapsed_ms=elapsed_ms,
                )
            try:
                self.verify_bound_state()
            except DirectorError as exc:
                raise DirectorBackendFailure(
                    str(exc),
                    code=exc.code,
                    raw_output=stdout,
                    elapsed_ms=elapsed_ms,
                ) from exc
            if process.returncode != 0:
                stderr_file.seek(0)
                stderr = stderr_file.read(4096).decode("utf-8", errors="replace")
                compact = " ".join(stderr.splitlines())
                raise DirectorBackendFailure(
                    f"director command exited {process.returncode}: {compact}",
                    code="director_command_failed",
                    raw_output=stdout,
                    elapsed_ms=elapsed_ms,
                )
            return self._parse_exchange(stdout, elapsed_ms=elapsed_ms)

    def _sanitized_environment(self) -> dict[str, str]:
        inherited = {}
        for name in ("COMSPEC", "PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"):
            value = os.environ.get(name)
            if value is not None:
                inherited[name] = value
        inherited.update(
            {
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "NO_PROXY": "*",
                "no_proxy": "*",
            }
        )
        inherited.update(self._environment)
        return inherited

    @staticmethod
    def _parse_exchange(data: bytes, *, elapsed_ms: int) -> DirectorCompletion:
        try:
            exchange = load_json_bytes(data, source="director-command-stdout")
        except Exception as exc:
            raise DirectorBackendFailure(
                f"director command did not return strict JSON: {exc}",
                code="director_protocol_invalid",
                raw_output=data,
                elapsed_ms=elapsed_ms,
            ) from exc

        def fail(message: str, code: str = "director_protocol_invalid") -> None:
            raise DirectorBackendFailure(
                message,
                code=code,
                raw_output=data,
                elapsed_ms=elapsed_ms,
            )

        if not isinstance(exchange, dict) or set(exchange) != _EXCHANGE_KEYS:
            fail("director command exchange has an invalid closed-field inventory")
        if exchange.get("protocol") != "score-director-jsonl/v1":
            fail("director command exchange protocol mismatch")
        response = exchange.get("response")
        usage = exchange.get("usage")
        tool_calls = exchange.get("observed_tool_calls")
        if not isinstance(response, dict):
            fail("director response must be an object")
        if not isinstance(usage, dict) or set(usage) != {
            "input_tokens",
            "output_tokens",
            "external_cost_microusd",
        }:
            fail("director usage is invalid")
        numeric = [usage.get("input_tokens"), usage.get("output_tokens"), usage.get("external_cost_microusd")]
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in numeric):
            fail("director usage values must be non-negative integers")
        if not isinstance(tool_calls, list) or any(not isinstance(item, str) for item in tool_calls):
            fail("director observed_tool_calls must be strings")
        if tool_calls:
            raise DirectorBackendFailure(
                "Phase A director command reported a tool call",
                code="director_tool_call_forbidden",
                raw_output=data,
                elapsed_ms=elapsed_ms,
                observed_tool_calls=tuple(tool_calls),
            )
        model_id = exchange.get("model_id")
        model_revision = exchange.get("model_revision")
        if not isinstance(model_id, str) or not model_id:
            fail("director model_id is invalid")
        if not isinstance(model_revision, str) or not model_revision:
            fail("director model_revision is invalid")
        return DirectorCompletion(
            raw_exchange=data,
            agent_response=response,
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            elapsed_ms=elapsed_ms,
            external_cost_microusd=usage["external_cost_microusd"],
            model_id=model_id,
            model_revision=model_revision,
            observed_tool_calls=tuple(tool_calls),
        )


def _spooled_output(handle: BinaryIO, *, max_bytes: int) -> tuple[bytes, bool]:
    """Read bounded stdout or retain only exact digest/size evidence."""

    handle.flush()
    handle.seek(0, os.SEEK_END)
    byte_count = handle.tell()
    handle.seek(0)
    if byte_count <= max_bytes:
        return handle.read(), False
    digest = hashlib.sha256()
    while True:
        block = handle.read(1024 * 1024)
        if not block:
            break
        digest.update(block)
    return (
        canonical_bytes(
            {
                "protocol": "score-director-oversize-response/v1",
                "observed_sha256": f"sha256:{digest.hexdigest()}",
                "observed_byte_count": byte_count,
                "retention": "digest_only_output_exceeded_frozen_ceiling",
            }
        ),
        True,
    )


def directory_manifest_sha256(root: Path | str) -> str:
    """Hash the complete regular-file inventory below one frozen runtime root."""

    candidate = Path(root)
    if candidate.is_symlink() or not candidate.is_dir():
        raise BoundaryError(f"director runtime root is unsafe: {candidate}")
    records: list[dict[str, str]] = []
    for entry in sorted(candidate.rglob("*"), key=lambda item: item.as_posix()):
        if entry.is_symlink():
            raise BoundaryError(f"director runtime manifest forbids symlinks: {entry}")
        if entry.is_dir():
            continue
        if not entry.is_file():
            raise BoundaryError(f"director runtime manifest found a non-file: {entry}")
        records.append(
            {
                "path": entry.relative_to(candidate).as_posix(),
                "sha256": file_sha256(entry),
            }
        )
    return canonical_sha256(
        {
            "protocol": "score-director-working-directory-manifest/v1",
            "files": records,
        }
    )
