from __future__ import annotations

import argparse
import array
import ctypes
import json
import math
import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from score_matter.canonical import (
    canonical_sha256,
    file_sha256,
    load_json_file,
    write_canonical_no_replace,
)
from score_matter.errors import BoundaryError, IntegrityError, ScoreMatterError


PLAN_SCHEMA = "score-sa3-boundary-plan/v1"
EXPERIMENT_PREFIX = ".local/experiments/"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
ATTEMPT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
PHASES = {"calibration", "phase1a", "phase1b"}
KINDS = {"text_to_audio", "audio_to_audio", "inpaint", "tail_inpaint"}
FINAL_ATTEMPT_STATES = {"complete", "failed", "blocked_by_dependency", "timed_out"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _expect_object(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BoundaryError(f"{label} must be an object", code="pilot_plan_invalid")
    return value


def _expect_keys(
    document: dict[str, Any],
    *,
    required: Iterable[str],
    optional: Iterable[str] = (),
    label: str,
) -> None:
    required_set = set(required)
    allowed = required_set | set(optional)
    missing = sorted(required_set - document.keys())
    unknown = sorted(document.keys() - allowed)
    if missing or unknown:
        raise BoundaryError(
            f"{label} keys invalid: missing={missing} unknown={unknown}",
            code="pilot_plan_invalid",
        )


def _expect_id(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or ID_PATTERN.fullmatch(value) is None:
        raise BoundaryError(f"{label} is not a safe ID: {value!r}", code="pilot_plan_invalid")
    return value


def _expect_attempt_id(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or ATTEMPT_ID_PATTERN.fullmatch(value) is None:
        raise BoundaryError(
            f"{label} is not a safe attempt ID: {value!r}", code="pilot_plan_invalid"
        )
    return value


def _expect_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise BoundaryError(f"{label} must be sha256:<lowercase-hex>", code="pilot_plan_invalid")
    return value


def _expect_int(value: Any, *, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise BoundaryError(
            f"{label} must be an integer from {minimum} through {maximum}",
            code="pilot_plan_invalid",
        )
    return value


def _expect_number(value: Any, *, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BoundaryError(f"{label} must be numeric", code="pilot_plan_invalid")
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise BoundaryError(
            f"{label} must be finite and from {minimum} through {maximum}",
            code="pilot_plan_invalid",
        )
    return result


def resolve_repo_path(repo: Path, logical: str, *, required_prefix: str | None = None) -> Path:
    if not isinstance(logical, str) or not logical or "\\" in logical or "\x00" in logical:
        raise BoundaryError(f"unsafe repository path: {logical!r}", code="pilot_path_invalid")
    candidate_path = Path(logical)
    if candidate_path.is_absolute() or any(part in {"", ".", ".."} for part in candidate_path.parts):
        raise BoundaryError(f"path must be normalized and relative: {logical!r}", code="pilot_path_invalid")
    normalized = candidate_path.as_posix()
    if required_prefix is not None and not normalized.startswith(required_prefix):
        raise BoundaryError(
            f"path must start with {required_prefix!r}: {logical!r}",
            code="pilot_path_invalid",
        )
    resolved_repo = repo.resolve()
    result = (resolved_repo / candidate_path).resolve(strict=False)
    try:
        result.relative_to(resolved_repo)
    except ValueError as exc:
        raise BoundaryError(f"path escapes repository: {logical!r}", code="pilot_path_invalid") from exc
    return result


@dataclass(frozen=True)
class ValidatedPlan:
    document: dict[str, Any]
    repo: Path
    plan_path: Path
    experiment_root: Path
    sa3_root: Path
    python_path: Path
    script_path: Path
    spec_path: Path
    attempts: dict[str, dict[str, Any]]


def validate_plan(plan_path: Path, *, repo: Path | None = None) -> ValidatedPlan:
    plan_path = plan_path.resolve()
    repo = (repo or Path(__file__).resolve().parents[1]).resolve()
    document = _expect_object(load_json_file(plan_path), label="plan")
    _expect_keys(
        document,
        required=(
            "schema",
            "experiment_id",
            "status",
            "spec",
            "runtime",
            "terms",
            "execution",
            "review",
            "attempts",
        ),
        label="plan",
    )
    if document["schema"] != PLAN_SCHEMA:
        raise BoundaryError(f"unknown pilot plan schema: {document['schema']!r}", code="pilot_plan_invalid")
    experiment_id = _expect_id(document["experiment_id"], label="experiment_id")
    if document["status"] not in {"draft", "frozen"}:
        raise BoundaryError("plan status must be draft or frozen", code="pilot_plan_invalid")

    spec = _expect_object(document["spec"], label="spec")
    _expect_keys(spec, required=("path", "sha256"), label="spec")
    spec_path = resolve_repo_path(repo, spec["path"], required_prefix="spec/")
    _expect_sha256(spec["sha256"], label="spec.sha256")

    runtime = _expect_object(document["runtime"], label="runtime")
    _expect_keys(
        runtime,
        required=("source_root", "source_commit", "sa3_root", "python", "script", "components"),
        label="runtime",
    )
    source_root = resolve_repo_path(repo, runtime["source_root"], required_prefix="models/")
    sa3_root = resolve_repo_path(repo, runtime["sa3_root"], required_prefix="models/")
    python_path = resolve_repo_path(repo, runtime["python"], required_prefix="models/")
    script_path = resolve_repo_path(repo, runtime["script"], required_prefix="models/")
    if not isinstance(runtime["source_commit"], str) or re.fullmatch(r"[0-9a-f]{40}", runtime["source_commit"]) is None:
        raise BoundaryError("runtime.source_commit must be a 40-character lowercase Git hash", code="pilot_plan_invalid")
    if source_root != (repo / runtime["source_root"]).resolve(strict=False):
        raise BoundaryError("runtime source path changed during resolution", code="pilot_path_invalid")
    components = runtime["components"]
    if not isinstance(components, list) or not components:
        raise BoundaryError("runtime.components must be a non-empty array", code="pilot_plan_invalid")
    component_paths: set[str] = set()
    for index, value in enumerate(components):
        component = _expect_object(value, label=f"runtime.components[{index}]")
        _expect_keys(component, required=("path", "bytes", "sha256"), label=f"runtime.components[{index}]")
        logical = component["path"]
        resolve_repo_path(repo, logical, required_prefix="models/")
        if logical in component_paths:
            raise BoundaryError(f"duplicate component path: {logical}", code="pilot_plan_invalid")
        component_paths.add(logical)
        _expect_int(component["bytes"], label=f"component {logical} bytes", minimum=1, maximum=20_000_000_000)
        _expect_sha256(component["sha256"], label=f"component {logical} sha256")

    terms = _expect_object(document["terms"], label="terms")
    _expect_keys(
        terms,
        required=("intended_use", "review_state", "review_basis", "sources"),
        label="terms",
    )
    if terms["intended_use"] != "local_internal_evaluation":
        raise BoundaryError("pilot terms intended_use must be local_internal_evaluation", code="pilot_plan_invalid")
    if terms["review_state"] not in {"pending", "accepted_for_local_evaluation_only"}:
        raise BoundaryError("unsupported terms review_state", code="pilot_plan_invalid")
    if not isinstance(terms["review_basis"], str) or not terms["review_basis"].strip():
        raise BoundaryError("terms.review_basis must be non-empty", code="pilot_plan_invalid")
    if not isinstance(terms["sources"], list) or not terms["sources"]:
        raise BoundaryError("terms.sources must be non-empty", code="pilot_plan_invalid")
    for index, source in enumerate(terms["sources"]):
        item = _expect_object(source, label=f"terms.sources[{index}]")
        _expect_keys(
            item,
            required=(
                "name",
                "url",
                "observed_revision",
                "retrieved_on",
                "snapshot_path",
                "sha256",
            ),
            label=f"terms.sources[{index}]",
        )
        for field in ("name", "url", "observed_revision", "retrieved_on", "snapshot_path"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise BoundaryError(f"terms source {field} must be non-empty", code="pilot_plan_invalid")
        snapshot_path = resolve_repo_path(repo, item["snapshot_path"])
        snapshot_logical = snapshot_path.relative_to(repo).as_posix()
        if not (
            snapshot_logical.startswith(f"{EXPERIMENT_PREFIX}{experiment_id}/plan/terms-snapshots/")
            or snapshot_logical == "models/stable-audio-3/LICENSE"
        ):
            raise BoundaryError(
                f"terms snapshot is outside the allowed private roots: {item['snapshot_path']}",
                code="pilot_path_invalid",
            )
        _expect_sha256(item["sha256"], label=f"terms source {item['name']} sha256")

    execution = _expect_object(document["execution"], label="execution")
    _expect_keys(
        execution,
        required=(
            "experiment_root",
            "dit",
            "decoder",
            "precision",
            "steps",
            "threads",
            "free_models",
            "calibration_timeout_seconds",
            "attempt_timeout_seconds",
            "minimum_free_bytes",
            "offline_environment",
        ),
        label="execution",
    )
    expected_root = f"{EXPERIMENT_PREFIX}{experiment_id}"
    if execution["experiment_root"] != expected_root:
        raise BoundaryError(
            f"experiment_root must be exactly {expected_root!r}", code="pilot_plan_invalid"
        )
    experiment_root = resolve_repo_path(repo, expected_root, required_prefix=EXPERIMENT_PREFIX)
    if execution["dit"] != "medium" or execution["decoder"] != "same-l" or execution["precision"] != "fp32":
        raise BoundaryError("this pilot freezes medium/same-l/fp32", code="pilot_plan_invalid")
    _expect_int(execution["steps"], label="steps", minimum=1, maximum=100)
    _expect_int(execution["threads"], label="threads", minimum=1, maximum=64)
    if execution["free_models"] is not True:
        raise BoundaryError("free_models must remain true", code="pilot_plan_invalid")
    _expect_int(execution["calibration_timeout_seconds"], label="calibration timeout", minimum=1, maximum=3600)
    _expect_int(execution["attempt_timeout_seconds"], label="attempt timeout", minimum=1, maximum=7200)
    _expect_int(execution["minimum_free_bytes"], label="minimum free bytes", minimum=1, maximum=10**15)
    offline_environment = execution["offline_environment"]
    if not isinstance(offline_environment, dict) or not offline_environment:
        raise BoundaryError("offline_environment must be a non-empty object", code="pilot_plan_invalid")
    for key, value in offline_environment.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise BoundaryError("offline_environment keys and values must be strings", code="pilot_plan_invalid")

    review = _expect_object(document["review"], label="review")
    _expect_keys(
        review,
        required=("blind_seed", "target_rms_dbfs", "sample_peak_ceiling_dbfs", "loop_repeats"),
        label="review",
    )
    _expect_int(review["blind_seed"], label="blind_seed", minimum=0, maximum=2**31 - 1)
    _expect_number(review["target_rms_dbfs"], label="target_rms_dbfs", minimum=-60, maximum=-3)
    _expect_number(review["sample_peak_ceiling_dbfs"], label="sample_peak_ceiling_dbfs", minimum=-20, maximum=-0.01)
    _expect_int(review["loop_repeats"], label="loop_repeats", minimum=2, maximum=16)

    attempts_value = document["attempts"]
    if not isinstance(attempts_value, list) or not attempts_value:
        raise BoundaryError("attempts must be a non-empty array", code="pilot_plan_invalid")
    attempts: dict[str, dict[str, Any]] = {}
    attempt_casefolds: set[str] = set()
    for index, value in enumerate(attempts_value):
        attempt = _expect_object(value, label=f"attempts[{index}]")
        _expect_keys(
            attempt,
            required=("id", "phase", "family", "kind", "prompt", "seed", "seconds", "cfg"),
            optional=("negative_prompt", "apg", "init_noise_level", "inpaint_range", "input_attempt"),
            label=f"attempts[{index}]",
        )
        attempt_id = _expect_attempt_id(attempt["id"], label=f"attempts[{index}].id")
        if attempt_id in attempts or attempt_id.casefold() in attempt_casefolds:
            raise BoundaryError(f"duplicate attempt ID: {attempt_id}", code="pilot_plan_invalid")
        attempt_casefolds.add(attempt_id.casefold())
        if attempt["phase"] not in PHASES or attempt["kind"] not in KINDS:
            raise BoundaryError(f"unsupported phase/kind for {attempt_id}", code="pilot_plan_invalid")
        _expect_id(attempt["family"], label=f"{attempt_id}.family")
        if not isinstance(attempt["prompt"], str) or not attempt["prompt"].strip():
            raise BoundaryError(f"{attempt_id}.prompt must be non-empty", code="pilot_plan_invalid")
        _expect_int(attempt["seed"], label=f"{attempt_id}.seed", minimum=0, maximum=2**32 - 1)
        _expect_int(attempt["seconds"], label=f"{attempt_id}.seconds", minimum=1, maximum=600)
        _expect_number(attempt["cfg"], label=f"{attempt_id}.cfg", minimum=-20, maximum=20)
        if "negative_prompt" in attempt:
            if not isinstance(attempt["negative_prompt"], str) or not attempt["negative_prompt"].strip():
                raise BoundaryError(f"{attempt_id}.negative_prompt must be non-empty", code="pilot_plan_invalid")
            if float(attempt["cfg"]) == 1.0:
                raise BoundaryError(
                    f"{attempt_id} supplies a negative prompt with cfg=1", code="pilot_plan_invalid"
                )
        if "apg" in attempt:
            _expect_number(attempt["apg"], label=f"{attempt_id}.apg", minimum=0, maximum=1)
            if float(attempt["cfg"]) == 1.0:
                raise BoundaryError(f"{attempt_id} supplies APG with cfg=1", code="pilot_plan_invalid")
        if attempt["kind"] == "audio_to_audio":
            _expect_number(
                attempt.get("init_noise_level"),
                label=f"{attempt_id}.init_noise_level",
                minimum=0.01,
                maximum=1.0,
            )
        if attempt["kind"] in {"audio_to_audio", "inpaint", "tail_inpaint"}:
            dependency = _expect_attempt_id(
                attempt.get("input_attempt"), label=f"{attempt_id}.input_attempt"
            )
            if dependency == attempt_id:
                raise BoundaryError(f"{attempt_id} cannot depend on itself", code="pilot_plan_invalid")
        if attempt["kind"] in {"inpaint", "tail_inpaint"}:
            inpaint_range = attempt.get("inpaint_range")
            if (
                not isinstance(inpaint_range, list)
                or len(inpaint_range) != 2
                or any(isinstance(item, bool) or not isinstance(item, (int, float)) for item in inpaint_range)
            ):
                raise BoundaryError(f"{attempt_id}.inpaint_range must be [start,end]", code="pilot_plan_invalid")
            start, end = map(float, inpaint_range)
            if not 0 <= start < end <= int(attempt["seconds"]):
                raise BoundaryError(f"{attempt_id}.inpaint_range is outside duration", code="pilot_plan_invalid")
        attempts[attempt_id] = attempt

    for attempt_id, attempt in attempts.items():
        dependency = attempt.get("input_attempt")
        if dependency is not None and dependency not in attempts:
            raise BoundaryError(f"{attempt_id} depends on unknown attempt {dependency}", code="pilot_plan_invalid")
    calibration = [item for item in attempts.values() if item["phase"] == "calibration"]
    phase1a = [item for item in attempts.values() if item["phase"] == "phase1a"]
    if len(calibration) != 1 or len(phase1a) != 18:
        raise BoundaryError(
            f"pilot requires one calibration and 18 phase1a attempts; got {len(calibration)} and {len(phase1a)}",
            code="pilot_plan_invalid",
        )

    return ValidatedPlan(
        document=document,
        repo=repo,
        plan_path=plan_path,
        experiment_root=experiment_root,
        sa3_root=sa3_root,
        python_path=python_path,
        script_path=script_path,
        spec_path=spec_path,
        attempts=attempts,
    )


def _git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _component_manifest(plan: ValidatedPlan, *, hash_files: bool) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for component in plan.document["runtime"]["components"]:
        path = resolve_repo_path(plan.repo, component["path"], required_prefix="models/")
        if path.is_symlink() or not path.is_file():
            raise IntegrityError(f"component is missing or not a regular file: {path}")
        stat = path.stat()
        if stat.st_size != component["bytes"]:
            raise IntegrityError(
                f"component byte count mismatch for {component['path']}: {stat.st_size}"
            )
        observed_hash = file_sha256(path) if hash_files else component["sha256"]
        if observed_hash != component["sha256"]:
            raise IntegrityError(f"component hash mismatch for {component['path']}")
        output.append(
            {
                "path": component["path"],
                "bytes": stat.st_size,
                "sha256": observed_hash,
                "mtime_ns_decimal": str(stat.st_mtime_ns),
            }
        )
    return output


def _token_counts(plan: ValidatedPlan) -> dict[str, Any]:
    code = (
        "import json,sys,sentencepiece as spm;"
        "d=json.load(open(sys.argv[1],encoding='utf-8'));"
        "s=spm.SentencePieceProcessor(model_file=sys.argv[2]);"
        "rows=[];"
        "[(rows.append({'id':a['id'],'prompt_tokens':len(s.encode(a['prompt'])),'negative_prompt_tokens':len(s.encode(a.get('negative_prompt',''))) if a.get('negative_prompt') else 0})) for a in d['attempts']];"
        "print(json.dumps(rows,separators=(',',':')))"
    )
    tokenizer = next(
        resolve_repo_path(plan.repo, item["path"], required_prefix="models/")
        for item in plan.document["runtime"]["components"]
        if item["path"].endswith("tokenizer.model")
    )
    result = subprocess.run(
        [str(plan.python_path), "-c", code, str(plan.plan_path), str(tokenizer)],
        cwd=plan.sa3_root,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    rows = json.loads(result.stdout)
    over_limit = [row["id"] for row in rows if max(row["prompt_tokens"], row["negative_prompt_tokens"]) > 256]
    if over_limit:
        raise BoundaryError(f"prompt token limit exceeded: {over_limit}", code="pilot_prompt_too_long")
    return {"tokenizer_limit": 256, "attempts": rows}


def _offline_probe(plan: ValidatedPlan) -> dict[str, Any]:
    code = (
        "import sys;from huggingface_hub import hf_hub_download;"
        "\ntry: hf_hub_download(repo_id='score-matter/offline-sentinel-never',filename='missing.bin')"
        "\nexcept Exception as e:"
        "\n chain=[];seen=set();cur=e"
        "\n while cur is not None and id(cur) not in seen: seen.add(id(cur));chain.append(type(cur).__name__+': '+str(cur));cur=cur.__cause__ or cur.__context__"
        "\n text=' | '.join(chain);print(text);sys.exit(0 if 'offlinemodeisenabled' in text.lower() or 'offline mode is enabled' in text.lower() else 2)"
        "\nelse: sys.exit(3)"
    )
    env = os.environ.copy()
    env.update(plan.document["execution"]["offline_environment"])
    result = subprocess.run(
        [str(plan.python_path), "-c", code],
        cwd=plan.sa3_root,
        env=env,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if result.returncode != 0:
        raise BoundaryError(
            f"offline missing-component probe failed closed incorrectly: exit={result.returncode}",
            code="pilot_isolation_failed",
        )
    return {
        "method": "hf_hub_missing_file_with_frozen_offline_environment",
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "silent_download_allowed": False,
    }


def run_preflight(plan: ValidatedPlan) -> dict[str, Any]:
    if plan.document["status"] != "frozen":
        raise BoundaryError("execution preflight requires a frozen plan", code="pilot_not_frozen")
    if plan.document["terms"]["review_state"] != "accepted_for_local_evaluation_only":
        raise BoundaryError("terms review is not accepted for local evaluation", code="pilot_terms_pending")
    if not plan.spec_path.is_file() or file_sha256(plan.spec_path) != plan.document["spec"]["sha256"]:
        raise IntegrityError("frozen specification digest mismatch")
    if not plan.python_path.is_file() or not plan.script_path.is_file():
        raise IntegrityError("frozen SA3 Python or script is missing")
    source_root = resolve_repo_path(
        plan.repo, plan.document["runtime"]["source_root"], required_prefix="models/"
    )
    source_commit = _git_output(source_root, "rev-parse", "HEAD")
    source_status = _git_output(source_root, "status", "--short")
    if source_commit != plan.document["runtime"]["source_commit"] or source_status:
        raise IntegrityError("SA3 source checkout is not the frozen clean revision")
    for logical in (
        plan.document["spec"]["path"],
        plan.document["execution"]["experiment_root"],
        plan.document["runtime"]["source_root"],
    ):
        ignored = subprocess.run(
            ["git", "-C", str(plan.repo), "check-ignore", "-q", "--", logical],
            check=False,
        )
        if ignored.returncode != 0:
            raise BoundaryError(f"required private path is not ignored: {logical}", code="pilot_privacy_failed")
    tracked_private = _git_output(plan.repo, "ls-files", "--", "spec", "models", ".local")
    if tracked_private:
        raise BoundaryError(f"private path is tracked: {tracked_private}", code="pilot_privacy_failed")
    free_bytes = shutil.disk_usage(plan.repo).free
    minimum_free = plan.document["execution"]["minimum_free_bytes"]
    if free_bytes < minimum_free:
        raise BoundaryError(
            f"free disk below plan minimum: {free_bytes} < {minimum_free}", code="pilot_disk_low"
        )
    components = _component_manifest(plan, hash_files=True)
    token_counts = _token_counts(plan)
    offline_probe = _offline_probe(plan)
    terms_sources: list[dict[str, Any]] = []
    for source in plan.document["terms"]["sources"]:
        snapshot = resolve_repo_path(plan.repo, source["snapshot_path"])
        if snapshot.is_symlink() or not snapshot.is_file():
            raise IntegrityError(f"terms snapshot is missing or unsafe: {source['snapshot_path']}")
        observed_hash = file_sha256(snapshot)
        if observed_hash != source["sha256"]:
            raise IntegrityError(f"terms snapshot hash mismatch: {source['snapshot_path']}")
        terms_sources.append({**source, "byte_count": snapshot.stat().st_size})
    record = {
        "schema": "score-sa3-boundary-preflight/v1",
        "experiment_id": plan.document["experiment_id"],
        "recorded_at": utc_now(),
        "plan_sha256": canonical_sha256(plan.document),
        "spec_sha256": plan.document["spec"]["sha256"],
        "source_commit": source_commit,
        "components": components,
        "token_counts": token_counts,
        "terms": {**plan.document["terms"], "sources": terms_sources},
        "host": {
            "platform": platform.platform(),
            "python": sys.version,
            "processor_count": os.cpu_count(),
            "locale": os.environ.get("LANG") or os.environ.get("LC_ALL") or "unknown",
            "free_bytes": free_bytes,
        },
        "isolation": {
            "network": "restricted_by_host_sandbox_and_offline_environment",
            "offline_environment": plan.document["execution"]["offline_environment"],
            "missing_component_probe": offline_probe,
            "silent_download_allowed": False,
        },
        "privacy": {
            "spec_ignored": True,
            "models_ignored": True,
            "experiment_root_ignored": True,
            "tracked_private_paths": [],
        },
        "status": "pass",
    }
    plan_root = plan.experiment_root / "plan"
    plan_root.mkdir(parents=True, exist_ok=True)
    write_canonical_no_replace(plan_root / "attempt-manifest.json", plan.document)
    write_canonical_no_replace(
        plan_root / "component-manifest.json",
        {
            "schema": "score-sa3-component-manifest/v1",
            "experiment_id": plan.document["experiment_id"],
            "source_commit": source_commit,
            "components": components,
        },
    )
    write_canonical_no_replace(
        plan_root / "terms-manifest.json",
        {
            "schema": "score-sa3-terms-manifest/v1",
            "experiment_id": plan.document["experiment_id"],
            **plan.document["terms"],
            "sources": terms_sources,
        },
    )
    write_canonical_no_replace(plan_root / "host-preflight.json", record)
    return record


def _load_preflight(plan: ValidatedPlan) -> dict[str, Any]:
    path = plan.experiment_root / "plan" / "host-preflight.json"
    record = _expect_object(load_json_file(path), label="preflight")
    if record.get("status") != "pass":
        raise BoundaryError("preflight did not pass", code="pilot_preflight_missing")
    if record.get("plan_sha256") != canonical_sha256(plan.document):
        raise IntegrityError("plan changed after preflight")
    if record.get("spec_sha256") != file_sha256(plan.spec_path):
        raise IntegrityError("specification changed after preflight")
    return record


def analyze_pcm16_wav(path: Path, *, expected_seconds: int | None = None) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise IntegrityError(f"WAV is missing or not a regular file: {path}")
    try:
        with wave.open(str(path), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            sample_rate = reader.getframerate()
            frame_count = reader.getnframes()
            compression = reader.getcomptype()
            payload = reader.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as exc:
        raise IntegrityError(f"cannot decode WAV {path}: {exc}") from exc
    expected_payload = frame_count * channels * sample_width
    if len(payload) != expected_payload:
        raise IntegrityError(
            f"incomplete WAV payload: expected {expected_payload}, read {len(payload)}"
        )
    samples = array.array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    channel_values = [samples[index::channels] for index in range(channels)] if channels else []
    all_count = len(samples)
    peak = max((abs(value) for value in samples), default=0)
    sum_samples = sum(samples)
    sum_squares = sum(value * value for value in samples)
    rms = math.sqrt(sum_squares / all_count) if all_count else 0.0
    rms_dbfs = 20 * math.log10(rms / 32768) if rms else None
    peak_dbfs = 20 * math.log10(peak / 32768) if peak else None
    crest_db = 20 * math.log10(peak / rms) if peak and rms else None
    full_scale_count = sum(1 for value in samples if value in {-32768, 32767})
    silence_count = sum(1 for value in samples if abs(value) <= 1)
    per_channel: list[dict[str, Any]] = []
    for index, values in enumerate(channel_values):
        count = len(values)
        channel_sum = sum(values)
        channel_squares = sum(value * value for value in values)
        channel_rms = math.sqrt(channel_squares / count) if count else 0.0
        per_channel.append(
            {
                "channel": index,
                "minimum": min(values, default=0),
                "maximum": max(values, default=0),
                "mean_normalized": channel_sum / count / 32768 if count else 0.0,
                "rms_dbfs": 20 * math.log10(channel_rms / 32768) if channel_rms else None,
                "stuck_constant": bool(values) and min(values) == max(values),
            }
        )
    stereo_correlation: float | None = None
    if channels == 2 and frame_count:
        left = channel_values[0]
        right = channel_values[1]
        mean_l = sum(left) / frame_count
        mean_r = sum(right) / frame_count
        covariance = sum((l - mean_l) * (r - mean_r) for l, r in zip(left, right))
        variance_l = sum((l - mean_l) ** 2 for l in left)
        variance_r = sum((r - mean_r) ** 2 for r in right)
        denominator = math.sqrt(variance_l * variance_r)
        stereo_correlation = covariance / denominator if denominator else None
    expected_frames = expected_seconds * 44100 if expected_seconds is not None else None
    hard_failures: list[str] = []
    if compression != "NONE":
        hard_failures.append("compressed_wav")
    if sample_width != 2:
        hard_failures.append("not_pcm16")
    if channels != 2:
        hard_failures.append("not_stereo")
    if sample_rate != 44100:
        hard_failures.append("wrong_sample_rate")
    if expected_frames is not None and frame_count != expected_frames:
        hard_failures.append("wrong_frame_count")
    if not all_count or rms == 0:
        hard_failures.append("digital_silence")
    if any(item["stuck_constant"] for item in per_channel):
        hard_failures.append("stuck_channel")
    return {
        "schema": "score-sa3-media-analysis/v1",
        "file_sha256": file_sha256(path),
        "byte_count": path.stat().st_size,
        "container": "wav",
        "codec": "pcm_s16le" if compression == "NONE" and sample_width == 2 else "unsupported",
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "frame_count": frame_count,
        "duration_seconds": frame_count / sample_rate if sample_rate else None,
        "sample_peak": peak,
        "sample_peak_dbfs": peak_dbfs,
        "full_scale_sample_count": full_scale_count,
        "full_scale_sample_ratio": full_scale_count / all_count if all_count else None,
        "rms_dbfs": rms_dbfs,
        "crest_factor_db": crest_db,
        "dc_offset_normalized": sum_samples / all_count / 32768 if all_count else None,
        "digital_silence_sample_ratio": silence_count / all_count if all_count else None,
        "stereo_correlation": stereo_correlation,
        "per_channel": per_channel,
        "unavailable": ["true_peak_dbtp", "integrated_lufs", "loudness_range", "spectral_narrow_band_prominence"],
        "hard_failures": hard_failures,
        "hard_pass": not hard_failures,
    }


def _windows_process_tree_working_set(process_id: int) -> int | None:
    if os.name != "nt":
        return None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", ctypes.c_ulong),
            ("PageFaultCount", ctypes.c_ulong),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.c_ulong),
            ("cntUsage", ctypes.c_ulong),
            ("th32ProcessID", ctypes.c_ulong),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", ctypes.c_ulong),
            ("cntThreads", ctypes.c_ulong),
            ("th32ParentProcessID", ctypes.c_ulong),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.c_ulong),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    # ctypes assumes C ``int`` for undeclared function signatures.  On 64-bit
    # Windows that truncates the HANDLE returned by OpenProcess and can make a
    # later query accidentally address an unrelated process.  Declare every
    # boundary explicitly before collecting evidence.
    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int
    kernel32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32FirstW.restype = ctypes.c_int
    kernel32.Process32NextW.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PROCESSENTRY32W),
    ]
    kernel32.Process32NextW.restype = ctypes.c_int
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == INVALID_HANDLE_VALUE:
        return None
    try:
        parent_by_pid: dict[int, int] = {}
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        present = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while present:
            parent_by_pid[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            present = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    descendants = {process_id}
    changed = True
    while changed:
        changed = False
        for child_id, parent_id in parent_by_pid.items():
            if parent_id in descendants and child_id not in descendants:
                descendants.add(child_id)
                changed = True

    observed = False
    total_working_set = 0
    for descendant_id in descendants:
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            descendant_id,
        )
        if not handle:
            continue
        try:
            counters = PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(counters)
            if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                total_working_set += int(counters.WorkingSetSize)
                observed = True
        finally:
            kernel32.CloseHandle(handle)
    return total_working_set if observed else None


def _dependency_raw(plan: ValidatedPlan, attempt: dict[str, Any]) -> Path:
    dependency = attempt.get("input_attempt")
    if dependency is None:
        raise BoundaryError("editing attempt has no input dependency", code="pilot_plan_invalid")
    path = plan.experiment_root / "attempts" / dependency / "raw.wav"
    status_path = plan.experiment_root / "attempts" / dependency / "status.json"
    if not status_path.is_file() or not path.is_file():
        raise BoundaryError(
            f"dependency {dependency} has no complete raw artifact", code="pilot_dependency_blocked"
        )
    status = _expect_object(load_json_file(status_path), label=f"dependency {dependency} status")
    if status.get("state") != "complete":
        raise BoundaryError(
            f"dependency {dependency} state is {status.get('state')!r}", code="pilot_dependency_blocked"
        )
    return path


def prepare_tail_input(source: Path, destination: Path, *, seconds: int) -> dict[str, Any]:
    analysis = analyze_pcm16_wav(source)
    if (
        analysis["codec"] != "pcm_s16le"
        or analysis["channels"] != 2
        or analysis["sample_rate_hz"] != 44100
    ):
        raise BoundaryError("tail input requires 44.1 kHz stereo PCM16", code="pilot_input_invalid")
    target_frames = seconds * 44100
    if analysis["frame_count"] >= target_frames:
        raise BoundaryError("tail input target must exceed source duration", code="pilot_input_invalid")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise IntegrityError(f"tail input already exists: {destination}")
    with wave.open(str(source), "rb") as reader:
        payload = reader.readframes(reader.getnframes())
    missing_frames = target_frames - analysis["frame_count"]
    with destination.open("xb") as destination_handle:
        with wave.open(destination_handle, "wb") as writer:
            writer.setnchannels(2)
            writer.setsampwidth(2)
            writer.setframerate(44100)
            writer.writeframes(payload)
            writer.writeframes(b"\x00" * missing_frames * 4)
    return {
        "schema": "score-sa3-tail-input/v1",
        "parent_sha256": analysis["file_sha256"],
        "output_sha256": file_sha256(destination),
        "source_frames": analysis["frame_count"],
        "target_frames": target_frames,
        "zero_padded_frames": missing_frames,
    }


def build_command(
    plan: ValidatedPlan, attempt: dict[str, Any], output: Path, *, input_audio: Path | None
) -> list[str]:
    execution = plan.document["execution"]
    command = [
        str(plan.python_path),
        str(plan.script_path),
        "--prompt",
        attempt["prompt"],
        "--dit",
        execution["dit"],
        "--decoder",
        execution["decoder"],
        "--precision",
        execution["precision"],
        "--seconds",
        str(attempt["seconds"]),
        "--steps",
        str(execution["steps"]),
        "--seed",
        str(attempt["seed"]),
        "--cfg",
        str(attempt["cfg"]),
        "--threads",
        str(execution["threads"]),
        "--free-models",
        "--out",
        str(output),
    ]
    if "negative_prompt" in attempt:
        command.extend(["--negative-prompt", attempt["negative_prompt"]])
    if "apg" in attempt:
        command.extend(["--apg", str(attempt["apg"])])
    if input_audio is not None:
        command.extend(["--init-audio", str(input_audio)])
    if attempt["kind"] == "audio_to_audio":
        command.extend(["--init-noise-level", str(attempt["init_noise_level"])])
    if attempt["kind"] in {"inpaint", "tail_inpaint"}:
        start, end = attempt["inpaint_range"]
        command.extend(["--inpaint-range", f"{start},{end}"])
    return command


def _safe_command_record(command: Sequence[str]) -> list[str]:
    return [str(item) for item in command]


def _require_phase_gate(plan: ValidatedPlan, attempt: dict[str, Any]) -> None:
    phase = attempt["phase"]
    if phase == "calibration":
        return
    if phase == "phase1b":
        raise BoundaryError(
            "phase1b is not authorized by this frozen pilot",
            code="pilot_phase_not_authorized",
        )
    calibration = next(
        item for item in plan.document["attempts"] if item["phase"] == "calibration"
    )
    status_path = (
        plan.experiment_root / "attempts" / calibration["id"] / "status.json"
    )
    if not status_path.is_file():
        raise BoundaryError(
            "phase1a requires a completed calibration",
            code="pilot_calibration_gate",
        )
    status = _expect_object(load_json_file(status_path), label="calibration status")
    wall_seconds = status.get("wall_seconds")
    if (
        status.get("state") != "complete"
        or isinstance(wall_seconds, bool)
        or not isinstance(wall_seconds, (int, float))
        or not math.isfinite(float(wall_seconds))
        or float(wall_seconds)
        > plan.document["execution"]["calibration_timeout_seconds"]
    ):
        raise BoundaryError(
            "phase1a calibration did not satisfy the frozen time and media gate",
            code="pilot_calibration_gate",
        )


def execute_attempt(plan: ValidatedPlan, attempt_id: str) -> dict[str, Any]:
    _load_preflight(plan)
    attempt = plan.attempts.get(attempt_id)
    if attempt is None:
        raise BoundaryError(f"unknown attempt: {attempt_id}", code="pilot_attempt_unknown")
    _require_phase_gate(plan, attempt)
    free_bytes = shutil.disk_usage(plan.repo).free
    if free_bytes < plan.document["execution"]["minimum_free_bytes"]:
        raise BoundaryError("free disk below experiment minimum", code="pilot_disk_low")
    _component_manifest(plan, hash_files=False)
    attempt_root = plan.experiment_root / "attempts" / attempt_id
    try:
        attempt_root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise IntegrityError(f"attempt directory already exists: {attempt_root}") from exc
    raw = attempt_root / "raw.wav"
    input_audio: Path | None = None
    input_record: dict[str, Any] | None = None
    try:
        if attempt["kind"] in {"audio_to_audio", "inpaint", "tail_inpaint"}:
            dependency = _dependency_raw(plan, attempt)
            if attempt["kind"] == "tail_inpaint":
                input_audio = attempt_root / "input-tail-padded.wav"
                input_record = prepare_tail_input(
                    dependency, input_audio, seconds=int(attempt["seconds"])
                )
                write_canonical_no_replace(attempt_root / "input-record.json", input_record)
            else:
                input_audio = dependency
                input_record = {
                    "input_attempt": attempt["input_attempt"],
                    "input_sha256": file_sha256(dependency),
                }
    except ScoreMatterError as exc:
        status = {
            "schema": "score-sa3-attempt-status/v1",
            "attempt_id": attempt_id,
            "state": "blocked_by_dependency",
            "recorded_at": utc_now(),
            "error_code": exc.code,
            "error": str(exc),
        }
        write_canonical_no_replace(attempt_root / "status.json", status)
        return status

    command = build_command(plan, attempt, raw, input_audio=input_audio)
    request = {
        "schema": "score-sa3-attempt-request/v1",
        "experiment_id": plan.document["experiment_id"],
        "plan_sha256": canonical_sha256(plan.document),
        "attempt": attempt,
        "command": _safe_command_record(command),
        "input": input_record,
        "output": str(raw),
    }
    write_canonical_no_replace(attempt_root / "request.json", request)
    env = os.environ.copy()
    env.update(plan.document["execution"]["offline_environment"])
    started_at = utc_now()
    started_clock = time.perf_counter()
    timeout = (
        plan.document["execution"]["calibration_timeout_seconds"]
        if attempt["phase"] == "calibration"
        else plan.document["execution"]["attempt_timeout_seconds"]
    )
    stdout_path = attempt_root / "stdout.txt"
    stderr_path = attempt_root / "stderr.txt"
    peak_working_set = 0
    timed_out = False
    with stdout_path.open("x", encoding="utf-8", newline="\n") as stdout_handle:
        with stderr_path.open("x", encoding="utf-8", newline="\n") as stderr_handle:
            process = subprocess.Popen(
                command,
                cwd=plan.sa3_root,
                env=env,
                stdout=stdout_handle,
                stderr=stderr_handle,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            while process.poll() is None:
                observed = _windows_process_tree_working_set(process.pid)
                if observed is not None:
                    peak_working_set = max(peak_working_set, observed)
                if time.perf_counter() - started_clock > timeout:
                    timed_out = True
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                    break
                time.sleep(0.2)
    ended_at = utc_now()
    wall_seconds = time.perf_counter() - started_clock
    analysis: dict[str, Any] | None = None
    analysis_error: str | None = None
    if raw.is_file():
        try:
            analysis = analyze_pcm16_wav(raw, expected_seconds=int(attempt["seconds"]))
            write_canonical_no_replace(attempt_root / "media-analysis.json", analysis)
        except ScoreMatterError as exc:
            analysis_error = f"{exc.code}: {exc}"
    state = "complete"
    if timed_out:
        state = "timed_out"
    elif process.returncode != 0 or analysis is None or not analysis["hard_pass"]:
        state = "failed"
    record = {
        "schema": "score-sa3-generation-record/v1",
        "experiment_id": plan.document["experiment_id"],
        "attempt_id": attempt_id,
        "phase": attempt["phase"],
        "family": attempt["family"],
        "kind": attempt["kind"],
        "plan_sha256": canonical_sha256(plan.document),
        "spec_sha256": plan.document["spec"]["sha256"],
        "source_commit": plan.document["runtime"]["source_commit"],
        "component_manifest_sha256": file_sha256(
            plan.experiment_root / "plan" / "component-manifest.json"
        ),
        "terms_manifest_sha256": file_sha256(
            plan.experiment_root / "plan" / "terms-manifest.json"
        ),
        "started_at": started_at,
        "ended_at": ended_at,
        "wall_seconds": wall_seconds,
        "peak_working_set_bytes": peak_working_set or None,
        "peak_working_set_method": (
            "max_sampled_aggregate_process_tree_working_set"
            if peak_working_set
            else "unavailable"
        ),
        "peak_working_set_sampling_interval_seconds": 0.2,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "timeout_seconds": timeout,
        "command": _safe_command_record(command),
        "offline_environment": plan.document["execution"]["offline_environment"],
        "input": input_record,
        "stdout_sha256": file_sha256(stdout_path),
        "stderr_sha256": file_sha256(stderr_path),
        "output_sha256": analysis["file_sha256"] if analysis is not None else None,
        "media_analysis_sha256": (
            file_sha256(attempt_root / "media-analysis.json") if analysis is not None else None
        ),
        "analysis_error": analysis_error,
        "state": state,
        "reproducibility": "best_effort",
        "bit_exact_regeneration_guaranteed": False,
        "orchestrator_sha256": file_sha256(Path(__file__).resolve()),
        "authority_class": "untrusted_candidate",
        "rights_reviewed_for_release": False,
    }
    write_canonical_no_replace(attempt_root / "generation-record.json", record)
    status = {
        "schema": "score-sa3-attempt-status/v1",
        "attempt_id": attempt_id,
        "state": state,
        "recorded_at": ended_at,
        "generation_record_sha256": file_sha256(attempt_root / "generation-record.json"),
        "output_sha256": record["output_sha256"],
        "wall_seconds": wall_seconds,
    }
    write_canonical_no_replace(attempt_root / "status.json", status)
    return status


def execute_phase(plan: ValidatedPlan, phase: str, *, resume: bool) -> list[dict[str, Any]]:
    if phase not in PHASES:
        raise BoundaryError(f"unknown phase: {phase}", code="pilot_phase_unknown")
    if phase == "phase1b":
        raise BoundaryError(
            "phase1b is not authorized by this frozen pilot",
            code="pilot_phase_not_authorized",
        )
    results: list[dict[str, Any]] = []
    for attempt in plan.document["attempts"]:
        if attempt["phase"] != phase:
            continue
        status_path = plan.experiment_root / "attempts" / attempt["id"] / "status.json"
        if status_path.exists():
            if not resume:
                raise IntegrityError(f"attempt already has status: {attempt['id']}")
            status = _expect_object(load_json_file(status_path), label="attempt status")
            if status.get("state") not in FINAL_ATTEMPT_STATES:
                raise IntegrityError(f"attempt has non-final state: {attempt['id']}")
            results.append(status)
            continue
        results.append(execute_attempt(plan, attempt["id"]))
        if phase == "calibration":
            result = results[-1]
            if result["state"] != "complete" or float(result["wall_seconds"]) > plan.document["execution"]["calibration_timeout_seconds"]:
                break
    return results


def rms_match_copy(
    source: Path,
    destination: Path,
    *,
    target_rms_dbfs: float,
    peak_ceiling_dbfs: float,
) -> dict[str, Any]:
    source_analysis = analyze_pcm16_wav(source)
    if source_analysis["codec"] != "pcm_s16le":
        raise BoundaryError("listening copy requires PCM16 input", code="pilot_input_invalid")
    with wave.open(str(source), "rb") as reader:
        channels = reader.getnchannels()
        sample_rate = reader.getframerate()
        frames = reader.getnframes()
        payload = reader.readframes(frames)
    samples = array.array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    rms = math.sqrt(sum(value * value for value in samples) / len(samples)) if samples else 0.0
    peak = max((abs(value) for value in samples), default=0)
    if rms == 0 or peak == 0:
        raise BoundaryError("cannot loudness-match digital silence", code="pilot_input_invalid")
    target_rms = 32768 * 10 ** (target_rms_dbfs / 20)
    ceiling = 32767 * 10 ** (peak_ceiling_dbfs / 20)
    gain = min(target_rms / rms, ceiling / peak)
    output = array.array("h")
    for value in samples:
        scaled = int(round(value * gain))
        output.append(max(-32768, min(32767, scaled)))
    if sys.byteorder != "little":
        output.byteswap()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise IntegrityError(f"listening copy already exists: {destination}")
    with destination.open("xb") as destination_handle:
        with wave.open(destination_handle, "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate)
            writer.writeframes(output.tobytes())
    result_analysis = analyze_pcm16_wav(destination)
    return {
        "schema": "score-sa3-listening-transform/v1",
        "algorithm": "linear_pcm16_rms_match_v1",
        "source_sha256": source_analysis["file_sha256"],
        "output_sha256": result_analysis["file_sha256"],
        "target_rms_dbfs": target_rms_dbfs,
        "sample_peak_ceiling_dbfs": peak_ceiling_dbfs,
        "applied_linear_gain": gain,
        "observed_output_rms_dbfs": result_analysis["rms_dbfs"],
        "observed_output_sample_peak_dbfs": result_analysis["sample_peak_dbfs"],
        "limitation": "RMS and sample-peak matching; not LUFS or true-peak normalization",
    }


def repeat_wav(source: Path, destination: Path, *, repeats: int) -> dict[str, Any]:
    analysis = analyze_pcm16_wav(source)
    with wave.open(str(source), "rb") as reader:
        channels = reader.getnchannels()
        sample_width = reader.getsampwidth()
        sample_rate = reader.getframerate()
        frames = reader.getnframes()
        payload = reader.readframes(frames)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise IntegrityError(f"repeat preview already exists: {destination}")
    with destination.open("xb") as destination_handle:
        with wave.open(destination_handle, "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(sample_width)
            writer.setframerate(sample_rate)
            for _ in range(repeats):
                writer.writeframes(payload)
    return {
        "schema": "score-sa3-repeat-preview/v1",
        "source_sha256": analysis["file_sha256"],
        "output_sha256": file_sha256(destination),
        "repeats": repeats,
        "source_frames": frames,
        "output_frames": frames * repeats,
        "crossfade_applied": False,
        "seamless_claim": False,
    }


def _read_pcm16_samples(path: Path) -> tuple[dict[str, Any], array.array]:
    analysis = analyze_pcm16_wav(path)
    if analysis["codec"] != "pcm_s16le":
        raise BoundaryError("edit comparison requires PCM16 input", code="pilot_input_invalid")
    with wave.open(str(path), "rb") as reader:
        payload = reader.readframes(reader.getnframes())
    samples = array.array("h")
    samples.frombytes(payload)
    if sys.byteorder != "little":
        samples.byteswap()
    return analysis, samples


def analyze_edit_relationship(
    input_audio: Path,
    output_audio: Path,
    *,
    inpaint_range_seconds: Sequence[float] | None,
) -> dict[str, Any]:
    input_analysis, input_samples = _read_pcm16_samples(input_audio)
    output_analysis, output_samples = _read_pcm16_samples(output_audio)
    media_fields = ("sample_rate_hz", "channels", "frame_count", "codec")
    if any(input_analysis[field] != output_analysis[field] for field in media_fields):
        raise BoundaryError(
            "edit comparison requires matching input and output media",
            code="pilot_input_invalid",
        )
    sample_rate = int(input_analysis["sample_rate_hz"])
    channels = int(input_analysis["channels"])
    frame_count = int(input_analysis["frame_count"])
    if inpaint_range_seconds is None:
        ranges = [(0, frame_count)]
        comparison_scope = "full_file"
    else:
        if len(inpaint_range_seconds) != 2:
            raise BoundaryError("edit comparison range must have two values", code="pilot_input_invalid")
        start_seconds, end_seconds = map(float, inpaint_range_seconds)
        start_frame = round(start_seconds * sample_rate)
        end_frame = round(end_seconds * sample_rate)
        if not 0 <= start_frame < end_frame <= frame_count:
            raise BoundaryError("edit comparison range is outside audio", code="pilot_input_invalid")
        ranges = [(start_frame, end_frame)]
        comparison_scope = "inpaint_inside_outside"

    aggregates = {
        "inside": {"sample_count": 0, "changed_sample_count": 0, "sum_squared_difference": 0, "maximum_absolute_difference": 0},
        "outside": {"sample_count": 0, "changed_sample_count": 0, "sum_squared_difference": 0, "maximum_absolute_difference": 0},
    }
    for frame in range(frame_count):
        region = "inside" if any(start <= frame < end for start, end in ranges) else "outside"
        aggregate = aggregates[region]
        offset = frame * channels
        for channel in range(channels):
            difference = int(output_samples[offset + channel]) - int(input_samples[offset + channel])
            absolute = abs(difference)
            aggregate["sample_count"] += 1
            aggregate["sum_squared_difference"] += difference * difference
            if difference:
                aggregate["changed_sample_count"] += 1
            aggregate["maximum_absolute_difference"] = max(
                aggregate["maximum_absolute_difference"], absolute
            )

    region_results: dict[str, Any] = {}
    for name, aggregate in aggregates.items():
        count = aggregate.pop("sample_count")
        changed = aggregate.pop("changed_sample_count")
        squared = aggregate.pop("sum_squared_difference")
        rms = math.sqrt(squared / count) if count else 0.0
        region_results[name] = {
            "sample_count": count,
            "changed_sample_count": changed,
            "changed_sample_ratio": changed / count if count else None,
            "bit_exact": changed == 0,
            "maximum_absolute_difference": aggregate["maximum_absolute_difference"],
            "rms_difference_dbfs": 20 * math.log10(rms / 32768) if rms else None,
        }

    boundaries: list[dict[str, Any]] = []
    if inpaint_range_seconds is not None:
        for seconds in map(float, inpaint_range_seconds):
            frame = round(seconds * sample_rate)
            input_jump = None
            output_jump = None
            if 0 < frame < frame_count:
                input_jump = max(
                    abs(int(input_samples[frame * channels + channel]) - int(input_samples[(frame - 1) * channels + channel]))
                    for channel in range(channels)
                ) / 32768
                output_jump = max(
                    abs(int(output_samples[frame * channels + channel]) - int(output_samples[(frame - 1) * channels + channel]))
                    for channel in range(channels)
                ) / 32768
            boundaries.append(
                {
                    "seconds": seconds,
                    "frame": frame,
                    "input_adjacent_jump_normalized": input_jump,
                    "output_adjacent_jump_normalized": output_jump,
                    "audible_seam_verdict": "requires_human_listening",
                }
            )

    return {
        "schema": "score-sa3-edit-analysis/v1",
        "algorithm": "pcm16_parent_child_difference_v1",
        "input_sha256": input_analysis["file_sha256"],
        "output_sha256": output_analysis["file_sha256"],
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "frame_count": frame_count,
        "comparison_scope": comparison_scope,
        "inpaint_range_seconds": list(map(float, inpaint_range_seconds)) if inpaint_range_seconds is not None else None,
        "regions": region_results,
        "boundaries": boundaries,
        "musical_preservation_verdict": "requires_human_listening",
    }


def analyze_edit_attempt(plan: ValidatedPlan, attempt_id: str) -> dict[str, Any]:
    _load_preflight(plan)
    attempt = plan.attempts.get(attempt_id)
    if attempt is None:
        raise BoundaryError(f"unknown attempt: {attempt_id}", code="pilot_attempt_unknown")
    if attempt["kind"] not in {"audio_to_audio", "inpaint", "tail_inpaint"}:
        raise BoundaryError("attempt is not an editing probe", code="pilot_input_invalid")
    attempt_root = plan.experiment_root / "attempts" / attempt_id
    status = _expect_object(load_json_file(attempt_root / "status.json"), label="edit status")
    if status.get("state") != "complete":
        raise BoundaryError("edit attempt is not complete", code="pilot_review_blocked")
    generation_path = attempt_root / "generation-record.json"
    generation = _expect_object(load_json_file(generation_path), label="edit generation record")
    output_audio = attempt_root / "raw.wav"
    if generation.get("output_sha256") != file_sha256(output_audio):
        raise IntegrityError("edit output hash does not match its generation record")
    if attempt["kind"] == "tail_inpaint":
        input_audio = attempt_root / "input-tail-padded.wav"
        expected_input_hash = (generation.get("input") or {}).get("output_sha256")
    else:
        input_audio = _dependency_raw(plan, attempt)
        expected_input_hash = (generation.get("input") or {}).get("input_sha256")
    if expected_input_hash != file_sha256(input_audio):
        raise IntegrityError("edit input hash does not match its generation record")
    result = analyze_edit_relationship(
        input_audio,
        output_audio,
        inpaint_range_seconds=attempt.get("inpaint_range"),
    )
    result.update(
        {
            "experiment_id": plan.document["experiment_id"],
            "attempt_id": attempt_id,
            "family": attempt["family"],
            "kind": attempt["kind"],
            "generation_record_sha256": file_sha256(generation_path),
            "orchestrator_sha256": file_sha256(Path(__file__).resolve()),
        }
    )
    write_canonical_no_replace(attempt_root / "edit-analysis.json", result)
    return result


def _closed_phase_review_candidates(
    plan: ValidatedPlan,
    attempt_ids: Sequence[str],
) -> tuple[str, list[tuple[str, Path]]]:
    if len(attempt_ids) != len(set(attempt_ids)):
        raise BoundaryError("review attempt IDs must be unique", code="pilot_review_blocked")
    unknown = sorted(set(attempt_ids) - plan.attempts.keys())
    if unknown:
        raise BoundaryError(f"unknown review attempts: {unknown}", code="pilot_attempt_unknown")
    phases = {plan.attempts[attempt_id]["phase"] for attempt_id in attempt_ids}
    if phases != {"phase1a"}:
        raise BoundaryError(
            "this frozen review builder accepts exactly the closed phase1a inventory",
            code="pilot_review_blocked",
        )
    phase_attempts = [
        item for item in plan.document["attempts"] if item["phase"] == "phase1a"
    ]
    reviewable: list[tuple[str, Path]] = []
    noncomplete: list[str] = []
    for attempt in phase_attempts:
        attempt_id = attempt["id"]
        attempt_root = plan.experiment_root / "attempts" / attempt_id
        status_path = attempt_root / "status.json"
        if not status_path.is_file():
            raise BoundaryError(
                f"phase1a inventory is not closed: {attempt_id} has no status",
                code="pilot_review_blocked",
            )
        status = _expect_object(load_json_file(status_path), label=f"{attempt_id} status")
        if status.get("state") not in FINAL_ATTEMPT_STATES:
            raise BoundaryError(
                f"phase1a inventory is not closed: {attempt_id} is non-final",
                code="pilot_review_blocked",
            )
        if status.get("state") != "complete":
            noncomplete.append(attempt_id)
            continue
        raw = attempt_root / "raw.wav"
        generation = _expect_object(
            load_json_file(attempt_root / "generation-record.json"),
            label=f"{attempt_id} generation record",
        )
        analysis = analyze_pcm16_wav(raw, expected_seconds=int(attempt["seconds"]))
        if not analysis["hard_pass"] or generation.get("output_sha256") != analysis["file_sha256"]:
            raise IntegrityError(f"review candidate integrity failed: {attempt_id}")
        if status.get("output_sha256") != analysis["file_sha256"]:
            raise IntegrityError(f"review status hash mismatch: {attempt_id}")
        if attempt["kind"] in {"audio_to_audio", "inpaint", "tail_inpaint"}:
            edit_path = attempt_root / "edit-analysis.json"
            if not edit_path.is_file():
                raise BoundaryError(
                    f"review requires edit analysis for {attempt_id}",
                    code="pilot_review_blocked",
                )
            edit_analysis = _expect_object(
                load_json_file(edit_path), label=f"{attempt_id} edit analysis"
            )
            if edit_analysis.get("output_sha256") != analysis["file_sha256"]:
                raise IntegrityError(f"edit analysis output mismatch: {attempt_id}")
        reviewable.append((attempt_id, raw))
    expected_ids = {attempt_id for attempt_id, _ in reviewable}
    if set(attempt_ids) != expected_ids:
        raise BoundaryError(
            f"review must include every complete phase1a candidate; expected={sorted(expected_ids)} "
            f"received={sorted(set(attempt_ids))} noncomplete={noncomplete}",
            code="pilot_review_blocked",
        )
    return "phase1a", reviewable


def prepare_review(plan: ValidatedPlan, attempt_ids: Sequence[str]) -> dict[str, Any]:
    _load_preflight(plan)
    review = plan.document["review"]
    phase, candidates = _closed_phase_review_candidates(plan, attempt_ids)
    rng = random.Random(review["blind_seed"])
    shuffled = candidates[:]
    rng.shuffle(shuffled)
    raw_root = plan.experiment_root / "derived" / "blind-raw"
    listening_root = plan.experiment_root / "derived" / "listening"
    loop_root = plan.experiment_root / "derived" / "loop-previews"
    private_mapping: list[dict[str, Any]] = []
    blind_entries: list[dict[str, Any]] = []
    loop_entries: list[dict[str, Any]] = []
    for index, (attempt_id, source) in enumerate(shuffled, start=1):
        blind_id = f"candidate-{index:03d}"
        raw_destination = raw_root / f"{blind_id}.wav"
        raw_destination.parent.mkdir(parents=True, exist_ok=True)
        if raw_destination.exists():
            raise IntegrityError(f"blind raw copy already exists: {raw_destination}")
        shutil.copyfile(source, raw_destination)
        raw_analysis = analyze_pcm16_wav(raw_destination)
        destination = listening_root / f"{blind_id}.wav"
        transform = rms_match_copy(
            source,
            destination,
            target_rms_dbfs=float(review["target_rms_dbfs"]),
            peak_ceiling_dbfs=float(review["sample_peak_ceiling_dbfs"]),
        )
        transform_path = listening_root / f"{blind_id}.transform.json"
        write_canonical_no_replace(transform_path, transform)
        loop_entry: dict[str, Any] | None = None
        if plan.attempts[attempt_id]["family"] == "game-context":
            loop_destination = loop_root / f"{blind_id}.raw-repeat.wav"
            loop_transform = repeat_wav(
                source,
                loop_destination,
                repeats=int(review["loop_repeats"]),
            )
            loop_transform_path = loop_root / f"{blind_id}.transform.json"
            write_canonical_no_replace(loop_transform_path, loop_transform)
            loop_entry = {
                "blind_id": blind_id,
                "audio_path": loop_destination.relative_to(plan.experiment_root).as_posix(),
                "audio_sha256": loop_transform["output_sha256"],
                "transform_path": loop_transform_path.relative_to(plan.experiment_root).as_posix(),
                "transform_sha256": file_sha256(loop_transform_path),
                "seamless_claim": False,
            }
            loop_entries.append(loop_entry)
        private_mapping.append(
            {
                "blind_id": blind_id,
                "attempt_id": attempt_id,
                "family": plan.attempts[attempt_id]["family"],
                "seed": plan.attempts[attempt_id]["seed"],
                "source_sha256": transform["source_sha256"],
                "listening_sha256": transform["output_sha256"],
            }
        )
        blind_entries.append(
            {
                "blind_id": blind_id,
                "raw_audio_path": raw_destination.relative_to(plan.experiment_root).as_posix(),
                "raw_audio_sha256": raw_analysis["file_sha256"],
                "matched_audio_path": destination.relative_to(plan.experiment_root).as_posix(),
                "matched_audio_sha256": transform["output_sha256"],
                "transform_sha256": file_sha256(transform_path),
            }
        )
    review_root = plan.experiment_root / "review"
    review_root.mkdir(parents=True, exist_ok=True)
    mapping_document = {
        "schema": "score-sa3-blind-mapping/v1",
        "experiment_id": plan.document["experiment_id"],
        "phase": phase,
        "plan_sha256": canonical_sha256(plan.document),
        "entries": private_mapping,
    }
    reveal_commitment = canonical_sha256(mapping_document)
    write_canonical_no_replace(review_root / "reveal-mapping.private.json", mapping_document)
    commitment_document = {
        "schema": "score-sa3-reveal-commitment/v1",
        "experiment_id": plan.document["experiment_id"],
        "phase": phase,
        "reveal_commitment": reveal_commitment,
        "algorithm": "sha256_rfc8785_canonical_json",
        "mapping_path_after_sound_quality_review": "review/reveal-mapping.private.json",
    }
    write_canonical_no_replace(review_root / "reveal-commitment.json", commitment_document)
    blind_document = {
        "schema": "score-sa3-blind-manifest/v1",
        "experiment_id": plan.document["experiment_id"],
        "phase": phase,
        "attempt_denominator": len(
            [item for item in plan.document["attempts"] if item["phase"] == phase]
        ),
        "reviewable_candidates": len(blind_entries),
        "reveal_commitment": reveal_commitment,
        "raw_identity_copy_algorithm": "byte_exact_copy_v1",
        "matched_copy_algorithm": "linear_pcm16_rms_match_v1",
        "comparison_copy": "matched",
        "entries": blind_entries,
    }
    write_canonical_no_replace(review_root / "blind-manifest.json", blind_document)
    loop_document = {
        "schema": "score-sa3-loop-review-manifest/v1",
        "experiment_id": plan.document["experiment_id"],
        "phase": phase,
        "use_only_after_sound_quality_review": True,
        "entries": loop_entries,
    }
    write_canonical_no_replace(review_root / "loop-review-manifest.json", loop_document)
    draft = {
        "schema": "score-sa3-human-review-draft/v1",
        "experiment_id": plan.document["experiment_id"],
        "phase": phase,
        "blind_manifest_sha256": file_sha256(review_root / "blind-manifest.json"),
        "reveal_commitment": reveal_commitment,
        "automatically_prepared": True,
        "human_attestation": None,
        "instructions": {
            "sound_quality_first": True,
            "reveal_prompts_only_after_sound_quality": True,
            "matched_family_comparisons_use": "matched_audio_path",
            "start_at_low_playback_level": True,
            "one_listener_is_exploratory_only": True,
        },
        "entries": [
            {
                "blind_id": entry["blind_id"],
                "target_adherence_0_4": None,
                "musical_coherence_0_4": None,
                "artifact_severity_0_4": None,
                "harshness_severity_0_4": None,
                "game_context_fit_0_4": None,
                "dialogue_ui_occupancy": None,
                "vocal_state": None,
                "ending_anomaly": None,
                "loop_seam_fatigue_0_4": None,
                "instrument_decision": None,
                "notes": [],
            }
            for entry in blind_entries
        ],
    }
    write_canonical_no_replace(review_root / "review-draft.json", draft)
    return blind_document


def stage_existing_review(plan: ValidatedPlan) -> dict[str, Any]:
    _load_preflight(plan)
    review_root = plan.experiment_root / "review"
    blind_path = review_root / "blind-manifest.json"
    blind = _expect_object(load_json_file(blind_path), label="blind manifest")
    entries = blind.get("entries")
    if not isinstance(entries, list):
        raise BoundaryError("blind manifest entries are invalid", code="pilot_review_blocked")
    sound_entries: list[dict[str, Any]] = []
    loop_entries: list[dict[str, Any]] = []
    leaked_loop_condition = False
    for value in entries:
        entry = _expect_object(value, label="blind manifest entry")
        clean = {key: item for key, item in entry.items() if key != "loop_preview"}
        sound_entries.append(clean)
        loop = entry.get("loop_preview")
        if loop is not None:
            leaked_loop_condition = True
            loop_entries.append({"blind_id": entry.get("blind_id"), **_expect_object(loop, label="loop preview")})
    sound_document = {
        "schema": "score-sa3-sound-quality-manifest/v1",
        "experiment_id": plan.document["experiment_id"],
        "phase": blind.get("phase"),
        "attempt_denominator": blind.get("attempt_denominator"),
        "reviewable_candidates": blind.get("reviewable_candidates"),
        "reveal_commitment": blind.get("reveal_commitment"),
        "source_blind_manifest_sha256": file_sha256(blind_path),
        "condition_metadata_hidden": True,
        "comparison_copy": blind.get("comparison_copy"),
        "entries": sound_entries,
    }
    sound_path = review_root / "sound-quality-manifest.json"
    write_canonical_no_replace(sound_path, sound_document)
    loop_path = review_root / "loop-review-manifest.json"
    if not loop_entries and loop_path.is_file():
        loop_document = _expect_object(
            load_json_file(loop_path), label="loop review manifest"
        )
    else:
        loop_document = {
            "schema": "score-sa3-loop-review-manifest/v1",
            "experiment_id": plan.document["experiment_id"],
            "phase": blind.get("phase"),
            "use_only_after_sound_quality_review": True,
            "entries": loop_entries,
        }
        if loop_path.is_file():
            if canonical_sha256(load_json_file(loop_path)) != canonical_sha256(loop_document):
                raise IntegrityError("existing loop review manifest does not match staged review")
        else:
            write_canonical_no_replace(loop_path, loop_document)
    result = {
        "schema": "score-sa3-review-staging/v1",
        "experiment_id": plan.document["experiment_id"],
        "source_blind_manifest_sha256": file_sha256(blind_path),
        "sound_quality_manifest_sha256": file_sha256(sound_path),
        "loop_review_manifest_sha256": file_sha256(loop_path),
        "source_manifest_leaked_loop_condition": leaked_loop_condition,
        "first_stage_manifest": "review/sound-quality-manifest.json",
        "original_manifest_first_stage_disposition": (
            "do_not_use_for_first_stage_blind_review"
            if leaked_loop_condition
            else "equivalent_without_condition_metadata"
        ),
        "orchestrator_sha256": file_sha256(Path(__file__).resolve()),
    }
    write_canonical_no_replace(review_root / "blinding-correction.json", result)
    return result


def _provider_runtime_versions(plan: ValidatedPlan) -> dict[str, Any]:
    code = (
        "import importlib.metadata as m,json,platform,sys\n"
        "names=['ai-edge-litert','numpy','soundfile','sentencepiece','huggingface-hub']\n"
        "versions={}\n"
        "for name in names:\n"
        " try: versions[name]=m.version(name)\n"
        " except m.PackageNotFoundError: versions[name]=None\n"
        "print(json.dumps({'python_executable':sys.executable,'python_version':sys.version,'platform':platform.platform(),'packages':versions},separators=(',',':')))"
    )
    result = subprocess.run(
        [str(plan.python_path), "-c", code],
        cwd=plan.sa3_root,
        env={**os.environ, **plan.document["execution"]["offline_environment"]},
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    return _expect_object(json.loads(result.stdout), label="provider runtime versions")


def _numeric_summary(values: Sequence[float]) -> dict[str, float | None]:
    if not values:
        return {"minimum": None, "median": None, "maximum": None, "total": None}
    return {
        "minimum": min(values),
        "median": statistics.median(values),
        "maximum": max(values),
        "total": sum(values),
    }


def summarize_phase1a(plan: ValidatedPlan) -> dict[str, Any]:
    _load_preflight(plan)
    review_root = plan.experiment_root / "review"
    blind_path = review_root / "blind-manifest.json"
    commitment_path = review_root / "reveal-commitment.json"
    if not blind_path.is_file() or not commitment_path.is_file():
        raise BoundaryError("phase1a review package is missing", code="pilot_review_blocked")
    blind = _expect_object(load_json_file(blind_path), label="blind manifest")
    if blind.get("attempt_denominator") != 18 or blind.get("reviewable_candidates") != 18:
        raise BoundaryError("phase1a review denominator is not closed", code="pilot_review_blocked")

    current_components = _component_manifest(plan, hash_files=True)
    component_path = plan.experiment_root / "plan" / "component-manifest.json"
    component_manifest = _expect_object(load_json_file(component_path), label="component manifest")
    frozen_components = component_manifest.get("components")
    terms_current = []
    for source in plan.document["terms"]["sources"]:
        snapshot = resolve_repo_path(plan.repo, source["snapshot_path"])
        observed = file_sha256(snapshot)
        if observed != source["sha256"]:
            raise IntegrityError(f"postflight terms snapshot mismatch: {source['name']}")
        terms_current.append(
            {"name": source["name"], "snapshot_path": source["snapshot_path"], "sha256": observed}
        )
    source_root = resolve_repo_path(
        plan.repo, plan.document["runtime"]["source_root"], required_prefix="models/"
    )
    source_commit = _git_output(source_root, "rev-parse", "HEAD")
    source_status = _git_output(source_root, "status", "--short")
    if source_commit != plan.document["runtime"]["source_commit"] or source_status:
        raise IntegrityError("SA3 source changed before postflight")

    summary_root = plan.experiment_root / "summary"
    summary_root.mkdir(parents=True, exist_ok=True)
    runtime_postflight = {
        "schema": "score-sa3-runtime-postflight/v1",
        "experiment_id": plan.document["experiment_id"],
        "recorded_at": utc_now(),
        "plan_sha256": canonical_sha256(plan.document),
        "spec_sha256": plan.document["spec"]["sha256"],
        "source_commit": source_commit,
        "source_status": "clean",
        "components": current_components,
        "component_snapshot_unchanged_since_preflight": current_components == frozen_components,
        "terms_snapshots": terms_current,
        "provider_runtime_end_snapshot": _provider_runtime_versions(plan),
        "evidence_timing": "postflight_end_snapshot_not_contemporaneous_per_attempt",
        "offline_environment": plan.document["execution"]["offline_environment"],
        "network_activity_observation": "not_instrumented",
        "component_acquisition_observed": False,
        "component_mutation_observed_by_preflight_postflight_comparison": current_components != frozen_components,
        "orchestrator_sha256": file_sha256(Path(__file__).resolve()),
    }
    runtime_path = summary_root / "runtime-postflight.json"
    write_canonical_no_replace(runtime_path, runtime_postflight)
    runtime_hash = file_sha256(runtime_path)

    rows: list[dict[str, Any]] = []
    wall_values: list[float] = []
    memory_values: list[float] = []
    full_scale_attempts: list[str] = []
    attempt_addenda: list[dict[str, Any]] = []
    for attempt in plan.document["attempts"]:
        attempt_id = attempt["id"]
        attempt_root = plan.experiment_root / "attempts" / attempt_id
        status = _expect_object(load_json_file(attempt_root / "status.json"), label="attempt status")
        row: dict[str, Any] = {
            "attempt_id": attempt_id,
            "phase": attempt["phase"],
            "family": attempt["family"],
            "kind": attempt["kind"],
            "state": status.get("state"),
        }
        generation_path = attempt_root / "generation-record.json"
        if generation_path.is_file():
            generation = _expect_object(load_json_file(generation_path), label="generation record")
            media_path = attempt_root / "media-analysis.json"
            media = _expect_object(load_json_file(media_path), label="media analysis")
            wall = float(generation["wall_seconds"])
            memory = generation.get("peak_working_set_bytes")
            if attempt["phase"] == "phase1a":
                wall_values.append(wall)
                if isinstance(memory, int):
                    memory_values.append(float(memory))
            if attempt["phase"] == "phase1a" and media.get("full_scale_sample_count", 0):
                full_scale_attempts.append(attempt_id)
            edit_path = attempt_root / "edit-analysis.json"
            addendum = {
                "schema": "score-sa3-attempt-evidence-addendum/v1",
                "experiment_id": plan.document["experiment_id"],
                "attempt_id": attempt_id,
                "generation_record_sha256": file_sha256(generation_path),
                "runtime_postflight_sha256": runtime_hash,
                "working_directory": plan.document["runtime"]["sa3_root"],
                "provider_runtime_version_evidence": "shared_postflight_end_snapshot",
                "cpu_time": {"state": "not_implemented"},
                "network_activity": {"state": "not_instrumented"},
                "component_acquisition": {"state": "not_observed"},
                "unavailable_analysis": {
                    name: {"state": "not_implemented"}
                    for name in media.get("unavailable", [])
                },
                "edit_analysis_sha256": file_sha256(edit_path) if edit_path.is_file() else None,
                "authority_class": "untrusted_candidate_evidence_only",
            }
            addendum_path = attempt_root / "evidence-addendum.json"
            write_canonical_no_replace(addendum_path, addendum)
            attempt_addenda.append(
                {"attempt_id": attempt_id, "sha256": file_sha256(addendum_path)}
            )
            row.update(
                {
                    "wall_seconds": wall,
                    "peak_working_set_bytes": memory,
                    "raw_sha256": generation.get("output_sha256"),
                    "hard_media_pass": media.get("hard_pass"),
                    "rms_dbfs": media.get("rms_dbfs"),
                    "sample_peak_dbfs": media.get("sample_peak_dbfs"),
                    "full_scale_sample_count": media.get("full_scale_sample_count"),
                    "edit_analysis_sha256": addendum["edit_analysis_sha256"],
                }
            )
        rows.append(row)

    correction_path = plan.experiment_root / "attempts" / "cal-001" / "measurement-correction.json"
    experiment_bytes = sum(
        path.stat().st_size for path in plan.experiment_root.rglob("*") if path.is_file()
    )
    result = {
        "schema": "score-sa3-phase1a-execution-summary/v1",
        "experiment_id": plan.document["experiment_id"],
        "recorded_at": utc_now(),
        "plan_sha256": canonical_sha256(plan.document),
        "spec_sha256": plan.document["spec"]["sha256"],
        "phase1a": {
            "attempt_denominator": 18,
            "complete": sum(row["phase"] == "phase1a" and row["state"] == "complete" for row in rows),
            "noncomplete": sum(row["phase"] == "phase1a" and row["state"] != "complete" for row in rows),
            "hard_media_all_pass": all(
                row.get("hard_media_pass") is True for row in rows if row["phase"] == "phase1a"
            ),
            "wall_seconds": _numeric_summary(wall_values),
            "peak_working_set_bytes": _numeric_summary(memory_values),
            "digital_full_scale_attempts": full_scale_attempts,
        },
        "calibration": {
            "attempt_id": "cal-001",
            "measurement_correction_sha256": file_sha256(correction_path) if correction_path.is_file() else None,
            "original_peak_working_set_disposition": "invalid_do_not_use" if correction_path.is_file() else "uncorrected",
        },
        "runtime_postflight_sha256": runtime_hash,
        "blind_manifest_sha256": file_sha256(blind_path),
        "reveal_commitment_sha256": file_sha256(commitment_path),
        "attempt_addenda": attempt_addenda,
        "experiment_bytes_before_this_summary": experiment_bytes,
        "experiment_budget_bytes": 512 * 1024 * 1024,
        "within_experiment_budget": experiment_bytes < 512 * 1024 * 1024,
        "attempts": rows,
        "human_review_state": "pending",
        "capability_decisions": "not_assigned",
        "phase1b_authorized": False,
        "consumer_game_status": "not_reviewed_not_copied_not_approved",
    }
    write_canonical_no_replace(summary_root / "phase1a-execution.json", result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a frozen, external Stable Audio 3 capability pilot without registering a provider."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="Validate a private pilot plan.")
    validate.add_argument("--plan", type=Path, required=True)
    preflight = commands.add_parser("preflight", help="Freeze and verify local execution evidence.")
    preflight.add_argument("--plan", type=Path, required=True)
    run = commands.add_parser("run", help="Run exactly one frozen attempt.")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--attempt", required=True)
    phase = commands.add_parser("run-phase", help="Run one frozen phase in manifest order.")
    phase.add_argument("--plan", type=Path, required=True)
    phase.add_argument("--phase", choices=sorted(PHASES), required=True)
    phase.add_argument("--resume", action="store_true")
    analyze = commands.add_parser("analyze", help="Analyze one PCM16 WAV without changing it.")
    analyze.add_argument("wav", type=Path)
    analyze.add_argument("--expected-seconds", type=int)
    analyze_edit = commands.add_parser(
        "analyze-edit", help="Create an immutable parent/child analysis for one edit attempt."
    )
    analyze_edit.add_argument("--plan", type=Path, required=True)
    analyze_edit.add_argument("--attempt", required=True)
    review = commands.add_parser("prepare-review", help="Create blind RMS-matched listening copies.")
    review.add_argument("--plan", type=Path, required=True)
    review.add_argument("--attempt", action="append", dest="attempts", required=True)
    summary = commands.add_parser(
        "summarize-phase1a",
        help="Bind the closed execution and review inventory without making capability judgments.",
    )
    summary.add_argument("--plan", type=Path, required=True)
    stage_review = commands.add_parser(
        "stage-review",
        help="Separate first-stage sound-quality review from later condition-specific listening.",
    )
    stage_review.add_argument("--plan", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "analyze":
            result = analyze_pcm16_wav(args.wav, expected_seconds=args.expected_seconds)
            print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            print(f"SCORE_SA3_ANALYZE_OK hard_pass={str(result['hard_pass']).lower()}")
            return 0 if result["hard_pass"] else 1
        plan = validate_plan(args.plan)
        if args.command == "validate":
            print(
                "SCORE_SA3_PLAN_OK "
                f"experiment={plan.document['experiment_id']} attempts={len(plan.attempts)} "
                f"sha256={canonical_sha256(plan.document)}"
            )
            return 0
        if args.command == "preflight":
            result = run_preflight(plan)
            print(
                "SCORE_SA3_PREFLIGHT_OK "
                f"experiment={plan.document['experiment_id']} "
                f"components={len(result['components'])}"
            )
            return 0
        if args.command == "run":
            result = execute_attempt(plan, args.attempt)
            print(
                "SCORE_SA3_ATTEMPT_DONE "
                f"attempt={args.attempt} state={result['state']} "
                f"wall_seconds={result.get('wall_seconds')}"
            )
            return 0 if result["state"] == "complete" else 1
        if args.command == "run-phase":
            results = execute_phase(plan, args.phase, resume=args.resume)
            complete = sum(item["state"] == "complete" for item in results)
            failed = len(results) - complete
            print(
                "SCORE_SA3_PHASE_DONE "
                f"phase={args.phase} complete={complete} noncomplete={failed}"
            )
            return 0 if failed == 0 else 1
        if args.command == "analyze-edit":
            result = analyze_edit_attempt(plan, args.attempt)
            print(
                "SCORE_SA3_EDIT_ANALYSIS_OK "
                f"attempt={args.attempt} scope={result['comparison_scope']}"
            )
            return 0
        if args.command == "prepare-review":
            result = prepare_review(plan, args.attempts)
            print(
                "SCORE_SA3_REVIEW_READY "
                f"candidates={len(result['entries'])} commitment={result['reveal_commitment']}"
            )
            return 0
        if args.command == "summarize-phase1a":
            result = summarize_phase1a(plan)
            print(
                "SCORE_SA3_PHASE1A_SUMMARY_OK "
                f"complete={result['phase1a']['complete']} "
                f"human_review={result['human_review_state']}"
            )
            return 0
        if args.command == "stage-review":
            result = stage_existing_review(plan)
            print(
                "SCORE_SA3_REVIEW_STAGED "
                f"condition_leak_corrected={str(result['source_manifest_leaked_loop_condition']).lower()}"
            )
            return 0
        parser.error(f"unsupported command: {args.command}")
    except (ScoreMatterError, OSError, subprocess.SubprocessError, ValueError) as exc:
        code = exc.code if isinstance(exc, ScoreMatterError) else "pilot_failed"
        message = " ".join(str(exc).splitlines())
        print(f"SCORE_SA3_ERROR code={code} message={message}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
