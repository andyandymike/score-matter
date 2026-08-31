from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .canonical import file_sha256
from .errors import BoundaryError, ProviderError
from .media import probe_pcm_wav


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_ROOT = (
    REPOSITORY_ROOT / "models" / "stable-audio-3" / "optimized" / "tflite"
)
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / ".local" / "authoring"
DEFAULT_TIMEOUT_SECONDS = 600
_MAX_PROMPT_CHARS = 4096
_MAX_SECONDS = 120
_MAX_SEED = 2**32 - 1
_OFFLINE_ENVIRONMENT = {
    "HF_HUB_OFFLINE": "1",
    "HF_DATASETS_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "HF_HUB_DISABLE_TELEMETRY": "1",
    "HF_HUB_DISABLE_IMPLICIT_TOKEN": "1",
    "DO_NOT_TRACK": "1",
}
_TEXT_TO_MUSIC_COMPONENTS = (
    Path("models/tokenizer.model"),
    Path("models/tflite/sa3-m/dit_fp32.tflite"),
    Path("models/tflite/same-l/dec_fp32.tflite"),
    Path("models/tflite/t5gemma/encoder_fp16.tflite"),
)


@dataclass(frozen=True)
class SA3GenerationSettings:
    seconds: int = 20
    seed: int | None = None
    steps: int = 8
    threads: int = 8
    cfg: float = 1.0
    apg: float | None = None
    negative_prompt: str | None = None
    play: bool = False
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS


@dataclass(frozen=True)
class SA3Runtime:
    root: Path
    python: Path
    script: Path


@dataclass(frozen=True)
class SA3GenerationResult:
    path: Path
    record_path: Path | None
    record_warning: str | None
    seed: int
    seconds: int
    wall_seconds: float
    media: dict[str, Any]
    sha256: str


def resolve_sa3_runtime(runtime_root: Path | None = None) -> SA3Runtime:
    configured = runtime_root
    if configured is None:
        environment_root = os.environ.get("SCORE_MATTER_SA3_ROOT")
        configured = Path(environment_root) if environment_root else DEFAULT_RUNTIME_ROOT
    root = configured.expanduser().resolve(strict=False)
    script = root / "scripts" / "sa3_tflite.py"
    python_candidates = (
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
    )
    python = next((path for path in python_candidates if path.is_file()), None)
    missing = [str(path) for path in _TEXT_TO_MUSIC_COMPONENTS if not (root / path).is_file()]
    empty = [
        str(path)
        for path in _TEXT_TO_MUSIC_COMPONENTS
        if (root / path).is_file() and (root / path).stat().st_size <= 0
    ]
    if python is None or not script.is_file() or missing or empty:
        details: list[str] = []
        if python is None:
            details.append("runtime Python")
        if not script.is_file():
            details.append("sa3_tflite.py")
        if missing:
            details.append(f"missing components={missing}")
        if empty:
            details.append(f"empty components={empty}")
        raise ProviderError(
            f"SA3 Medium runtime is unavailable under {root}: {', '.join(details)}",
            code="sa3_runtime_unavailable",
        )
    return SA3Runtime(root=root, python=python, script=script)


def build_sa3_command(
    *,
    runtime: SA3Runtime,
    prompt: str,
    output: Path,
    settings: SA3GenerationSettings,
    seed: int,
) -> list[str]:
    _validate_prompt(prompt, label="prompt")
    _validate_settings(settings, seed=seed)
    command = [
        str(runtime.python),
        str(runtime.script),
        "--prompt",
        prompt,
        "--dit",
        "medium",
        "--decoder",
        "same-l",
        "--precision",
        "fp32",
        "--seconds",
        str(settings.seconds),
        "--steps",
        str(settings.steps),
        "--seed",
        str(seed),
        "--cfg",
        str(settings.cfg),
        "--threads",
        str(settings.threads),
        "--free-models",
        "--out",
        str(output),
    ]
    if settings.negative_prompt is not None:
        command.extend(["--negative-prompt", settings.negative_prompt])
    if settings.apg is not None:
        command.extend(["--apg", str(settings.apg)])
    if settings.play:
        command.append("--play")
    return command


def generate_sa3_wav(
    prompt: str,
    *,
    settings: SA3GenerationSettings | None = None,
    output: Path | None = None,
    output_root: Path | None = None,
    runtime_root: Path | None = None,
) -> SA3GenerationResult:
    """Run exactly one local SA3 process and return one playable WAV.

    This is the default fast-authoring path. It performs no Director evaluation,
    approval workflow, hidden retry, model download, or model-weight hashing.
    """

    clean_prompt = _validate_prompt(prompt, label="prompt")
    chosen = settings or SA3GenerationSettings()
    seed = chosen.seed if chosen.seed is not None else secrets.randbelow(_MAX_SEED + 1)
    _validate_settings(chosen, seed=seed)
    runtime = resolve_sa3_runtime(runtime_root)
    destination = (
        output.expanduser().resolve(strict=False)
        if output is not None
        else _default_output_path(
            clean_prompt,
            seed=seed,
            output_root=output_root or DEFAULT_OUTPUT_ROOT,
        )
    )
    _prepare_destination(destination)
    staging = _allocate_staging_path(destination)
    command = build_sa3_command(
        runtime=runtime,
        prompt=clean_prompt,
        output=staging,
        settings=chosen,
        seed=seed,
    )
    environment = os.environ.copy()
    environment.update(_OFFLINE_ENVIRONMENT)
    try:
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                command,
                cwd=runtime.root,
                env=environment,
                timeout=chosen.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(
                f"SA3 generation exceeded {chosen.timeout_seconds} seconds; no retry was attempted",
                code="sa3_generation_timed_out",
            ) from exc
        except OSError as exc:
            raise ProviderError(
                f"could not start SA3 generation: {exc}",
                code="sa3_generation_start_failed",
            ) from exc
        wall_seconds = time.perf_counter() - started
        if completed.returncode != 0:
            raise ProviderError(
                f"SA3 generation exited with code {completed.returncode}; no retry was attempted",
                code="sa3_generation_failed",
            )
        if not staging.is_file() or staging.stat().st_size <= 0:
            raise ProviderError(
                "SA3 reported success but did not write the requested WAV",
                code="sa3_output_missing",
            )
        media = probe_pcm_wav(staging)
        expected_frames = chosen.seconds * 44100
        expected_media = {
            "codec": "pcm_s16le",
            "sample_rate_hz": 44100,
            "channels": 2,
            "frame_count": expected_frames,
        }
        mismatches = {
            key: {"expected": value, "observed": media.get(key)}
            for key, value in expected_media.items()
            if media.get(key) != value
        }
        if mismatches:
            raise ProviderError(
                f"SA3 output media facts differ from the fast-path request: {mismatches}",
                code="sa3_output_invalid",
            )
        digest = file_sha256(staging)
        _publish_no_replace(staging=staging, destination=destination)
    finally:
        _discard_staging(staging)
        if output is None:
            _discard_empty_directory(destination.parent)
    record_path, record_warning = _write_local_record(
        record_root=DEFAULT_OUTPUT_ROOT / "records",
        destination=destination,
        prompt=clean_prompt,
        settings=chosen,
        seed=seed,
        runtime=runtime,
        command=command,
        wall_seconds=wall_seconds,
        media=media,
        digest=digest,
    )
    return SA3GenerationResult(
        path=destination,
        record_path=record_path,
        record_warning=record_warning,
        seed=seed,
        seconds=chosen.seconds,
        wall_seconds=wall_seconds,
        media=media,
        sha256=digest,
    )


def _validate_prompt(value: str, *, label: str) -> str:
    clean = value.strip()
    if not clean:
        raise BoundaryError(f"{label} must not be empty", code="generation_prompt_invalid")
    if len(clean) > _MAX_PROMPT_CHARS:
        raise BoundaryError(
            f"{label} exceeds {_MAX_PROMPT_CHARS} characters",
            code="generation_prompt_invalid",
        )
    return clean


def _validate_settings(settings: SA3GenerationSettings, *, seed: int) -> None:
    _bounded_int(settings.seconds, label="seconds", minimum=1, maximum=_MAX_SECONDS)
    _bounded_int(settings.steps, label="steps", minimum=1, maximum=100)
    _bounded_int(settings.threads, label="threads", minimum=1, maximum=64)
    _bounded_int(seed, label="seed", minimum=0, maximum=_MAX_SEED)
    _bounded_int(
        settings.timeout_seconds,
        label="timeout_seconds",
        minimum=1,
        maximum=86400,
    )
    if not -20.0 <= float(settings.cfg) <= 20.0:
        raise BoundaryError("cfg must be between -20 and 20", code="generation_settings_invalid")
    if settings.negative_prompt is not None:
        _validate_prompt(settings.negative_prompt, label="negative_prompt")
        if float(settings.cfg) == 1.0:
            raise BoundaryError(
                "negative_prompt requires cfg other than 1.0; the upstream runtime would ignore it",
                code="generation_settings_invalid",
            )
    if settings.apg is not None:
        if float(settings.cfg) == 1.0:
            raise BoundaryError(
                "apg requires cfg other than 1.0",
                code="generation_settings_invalid",
            )
        if not 0.0 <= float(settings.apg) <= 1.0:
            raise BoundaryError(
                "apg must be between 0 and 1",
                code="generation_settings_invalid",
            )


def _bounded_int(value: int, *, label: str, minimum: int, maximum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BoundaryError(
            f"{label} must be an integer between {minimum} and {maximum}",
            code="generation_settings_invalid",
        )


def _prepare_destination(destination: Path) -> None:
    if destination.suffix.casefold() != ".wav":
        raise BoundaryError("generation output must end in .wav", code="generation_output_invalid")
    if destination.exists() or destination.is_symlink():
        raise BoundaryError(
            f"generation output already exists: {destination}",
            code="destination_exists",
        )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BoundaryError(
            f"cannot prepare generation output directory: {destination.parent}: {exc}",
            code="generation_output_invalid",
        ) from exc


def _allocate_staging_path(destination: Path) -> Path:
    for _ in range(10):
        staging = destination.with_name(
            f".{destination.name}.{secrets.token_hex(8)}.tmp.wav"
        )
        try:
            with staging.open("xb"):
                pass
            return staging
        except FileExistsError:
            continue
        except OSError as exc:
            raise BoundaryError(
                f"cannot prepare temporary generation output: {staging}: {exc}",
                code="generation_output_invalid",
            ) from exc
    raise BoundaryError(
        f"could not allocate a unique temporary output beside {destination}",
        code="generation_output_invalid",
    )


def _publish_no_replace(*, staging: Path, destination: Path) -> None:
    try:
        os.link(staging, destination)
    except FileExistsError as exc:
        raise BoundaryError(
            f"generation output appeared while the model was running: {destination}",
            code="destination_exists",
        ) from exc
    except OSError as exc:
        raise ProviderError(
            f"could not atomically publish generated WAV: {exc}",
            code="generation_publish_failed",
        ) from exc


def _discard_staging(staging: Path) -> None:
    try:
        staging.unlink(missing_ok=True)
    except OSError:
        pass


def _discard_empty_directory(directory: Path) -> None:
    try:
        directory.rmdir()
    except OSError:
        pass


def _default_output_path(prompt: str, *, seed: int, output_root: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.casefold()).strip("-")[:36] or "bgm"
    run_root = output_root.expanduser().resolve(strict=False) / f"{timestamp}-{slug}-s{seed}"
    return run_root / "candidate.wav"


def _write_local_record(
    *,
    record_root: Path,
    destination: Path,
    prompt: str,
    settings: SA3GenerationSettings,
    seed: int,
    runtime: SA3Runtime,
    command: list[str],
    wall_seconds: float,
    media: dict[str, Any],
    digest: str,
) -> tuple[Path | None, str | None]:
    record_timestamp = datetime.now(timezone.utc)
    record_name = (
        f"{record_timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-"
        f"s{seed}-{digest.removeprefix('sha256:')[:12]}.generation.json"
    )
    record_path = record_root / record_name
    record = {
        "kind": "score-matter-fast-generation",
        "status": "candidate",
        "created_at": record_timestamp.isoformat().replace("+00:00", "Z"),
        "prompt": prompt,
        "negative_prompt": settings.negative_prompt,
        "settings": {
            "seconds": settings.seconds,
            "seed": seed,
            "steps": settings.steps,
            "threads": settings.threads,
            "cfg": settings.cfg,
            "apg": settings.apg,
        },
        "runtime": {
            "family": "stable-audio-3-medium",
            "dit": "medium",
            "decoder": "same-l",
            "precision": "fp32",
            "root": str(runtime.root),
            "offline": True,
            "component_check": "path_and_nonzero_size_only",
        },
        "command": command,
        "attempt_count": 1,
        "automatic_retries": 0,
        "wall_seconds": wall_seconds,
        "output": {
            "path": str(destination),
            "sha256": digest,
            "media": media,
        },
    }
    try:
        record_path.parent.mkdir(parents=True, exist_ok=True)
        with record_path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(record, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except OSError as exc:
        return None, f"candidate was generated but its optional local record failed: {exc}"
    return record_path, None
