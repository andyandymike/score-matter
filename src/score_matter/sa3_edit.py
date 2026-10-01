"""Optional SA3 inpainting adapter over the shared authoring contracts.

The model supplies a proposal. The core splice controls every written PCM frame.
No model imports, downloads or remote API calls occur in this adapter.
"""

from __future__ import annotations

import errno
import hashlib
import math
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from matter_audio_core.actions import AudioAttachment, Operation, OperationOutput, Registry
from matter_audio_core.artifacts import safe_path, stable_read
from matter_audio_core.composition import observed_changes, resolve_splice, splice
from matter_audio_core.contracts import digest, object_schema
from matter_audio_core.errors import AudioError
from matter_audio_core.execution import checkpoint
from matter_audio_core.fades import FRAME_COUNT, identity_mapping
from matter_audio_core.media import decode_wav, encode_wav, trim
from matter_audio_core.processes import run_process, temporary_process_directory

from .authoring import SA3GenerationSettings, _OFFLINE_ENVIRONMENT, build_sa3_command, resolve_sa3_runtime
from .errors import ScoreMatterError

PROFILE = "score-sa3-medium-inpaint-same-l-fp32/v1"
RATE, LATENT = 44100, 4096
COMPONENTS = ("models/tokenizer.model", "models/tflite/sa3-m/dit_fp32.tflite",
    "models/tflite/same-l/dec_fp32.tflite", "models/tflite/same-l/enc_fp32.tflite",
    "models/tflite/t5gemma/encoder_fp16.tflite")
PROMPT = {"type": "string", "minLength": 1, "maxLength": 4096, "pattern": r"\S"}
SCHEMA = object_schema({"prompt": PROMPT, "negative_prompt": PROMPT,
    "start_frame": FRAME_COUNT, "end_frame": FRAME_COUNT, "transition_frames": FRAME_COUNT,
    "seed": {"type": "integer", "minimum": 0, "maximum": 4294967295},
    "steps": {"type": "integer", "minimum": 1, "maximum": 50},
    "threads": {"type": "integer", "minimum": 1, "maximum": 32},
    "cfg": {"type": "number", "minimum": 0, "maximum": 20},
    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 3600}},
    ["prompt", "start_frame", "end_frame", "seed"])


def _runtime(root):
    try:
        runtime = resolve_sa3_runtime(root)
    except ScoreMatterError as exc:
        raise AudioError(exc.code, str(exc)) from exc
    encoder = runtime.root / COMPONENTS[3]
    if not encoder.is_file() or not encoder.stat().st_size:
        raise AudioError("sa3_encoder_unavailable", "Local inpainting requires the SAME-L encoder")
    try:
        driver = "".join(runtime.script.read_text(encoding="utf-8").split())
    except (OSError, UnicodeError) as exc:
        raise AudioError("sa3_driver_unavailable", "Local SA3 driver must be readable UTF-8 source") from exc
    required = ("SAMPLE_RATE=44100", "SAMPLES_PER_LATENT=4096",
        "int(round(inp_start_sec*SAMPLE_RATE/SAMPLES_PER_LATENT))",
        "int(round(inp_end_sec*SAMPLE_RATE/SAMPLES_PER_LATENT))",
        "int(np.ceil(seconds*SAMPLE_RATE/SAMPLES_PER_LATENT))")
    if not all(marker in driver for marker in required):
        raise AudioError("sa3_driver_unsupported", "Review this driver's time and mask semantics before using the inpaint profile")
    return runtime


def _stamp(path):
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _file_snapshot(path, root):
    path = safe_path(path)
    before = _stamp(path)
    hashed = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            checkpoint()
            hashed.update(chunk)
    if before != _stamp(path):
        raise AudioError("runtime_changed", "Backend component changed while hashing")
    return {"path": path.relative_to(root).as_posix(), "bytes": before[2], "sha256": hashed.hexdigest()}


@contextmanager
def _runtime_lock(root):
    # One lock per configured runtime, across sessions and workspaces. Never unlink.
    path = safe_path(Path(tempfile.gettempdir()) / ("matter-sa3-" + digest(str(root).encode())["hex"] + ".lock"))
    with path.open("a+b") as stream:
        try:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise AudioError("backend_busy", "Another local edit owns this SA3 runtime") from exc
            raise
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class SA3EditAdapter:
    def __init__(self, runtime_root=None):
        self.runtime_root = runtime_root
        self.cached_stamp = self.cached_snapshot = None

    def signature(self):
        runtime = _runtime(self.runtime_root)
        paths = {runtime.python, runtime.script, *(runtime.root / name for name in COMPONENTS)}
        for directory in (runtime.root / "scripts", runtime.root / "models/defs"):
            paths.update(directory.rglob("*.py"))
        config = runtime.root / ".venv/pyvenv.cfg"
        if config.is_file():
            paths.add(config)
        for library in (runtime.root / ".venv/Lib/site-packages", runtime.root / ".venv/lib"):
            if library.exists():
                paths.update(library.glob("*.dist-info/METADATA") if library.name == "site-packages"
                             else library.glob("python*/site-packages/*.dist-info/METADATA"))
        paths = sorted(paths)
        stamp = [(str(path), _stamp(path)) for path in paths]
        if stamp != self.cached_stamp:
            snapshot = {"method": "sa3-local-component-sha256/v1", "runtime_root": str(runtime.root),
                        "files": [_file_snapshot(path, runtime.root) for path in paths]}
            self.cached_stamp, self.cached_snapshot = stamp, snapshot
        return runtime, self.cached_snapshot

    def resolve(self, parameters, pcm):
        if (pcm.sample_rate, pcm.channels) != (RATE, 2) or not RATE <= pcm.frames <= 120 * RATE:
            raise AudioError("sa3_input_unsupported", "Inpaint accepts 1–120 seconds of 44.1 kHz stereo PCM16; decode explicitly first")
        start, end = parameters["start_frame"], parameters["end_frame"]
        if not 0 <= start < end <= pcm.frames:
            raise AudioError("invalid_range", "Requested edit must fit the input")
        if parameters.get("negative_prompt") is not None and parameters.get("cfg", 1) == 1:
            raise AudioError("invalid_request", "negative_prompt requires cfg other than 1")
        if "\0" in parameters["prompt"] or "\0" in parameters.get("negative_prompt", ""):
            raise AudioError("invalid_request", "Prompts must not contain NUL characters")
        seconds = math.ceil(pcm.frames / RATE)
        start_text, end_text = format(start / RATE, ".17g"), format(end / RATE, ".17g")
        latent_start = max(0, int(round(float(start_text) * RATE / LATENT)))
        latent_end = min(math.ceil(seconds * RATE / LATENT), int(round(float(end_text) * RATE / LATENT)))
        if latent_start >= latent_end:
            raise AudioError("model_mask_empty", "Requested edit collapses to an empty SA3 latent mask")
        transition = parameters.get("transition_frames", min(882, (end - start) // 2))
        splice_plan = resolve_splice({"start_frame": start, "end_frame": end, "transition_frames": transition}, [pcm, pcm])
        _, signature = self.signature()
        window = {"start_frame": start, "end_frame": end}
        return {"prompt": parameters["prompt"], "negative_prompt": parameters.get("negative_prompt"),
            "seed": parameters["seed"], "steps": parameters.get("steps", 8), "threads": parameters.get("threads", 8),
            "cfg": parameters.get("cfg", 1), "timeout_seconds": parameters.get("timeout_seconds", 600),
            "model_seconds": seconds, "inpaint_argument": start_text + "," + end_text,
            "context_read": {"start_frame": 0, "end_frame": pcm.frames}, "requested_edit": window,
            "model_mask": {"latent_start": latent_start, "latent_end": latent_end, "samples_per_latent": LATENT,
                "start_frame": latent_start * LATENT, "end_frame": latent_end * LATENT, "rounding": "python-round-ties-to-even/v1"},
            "allowed_write": [window], "splice": splice_plan, "backend": signature}

    def execute(self, parameters, pcm):
        runtime, signature = self.signature()
        if signature != parameters["backend"]:
            raise AudioError("runtime_changed", "SA3 runtime differs from the resolved backend")
        with _runtime_lock(runtime.root), temporary_process_directory(prefix="score-inpaint-") as directory:
            source, destination = directory / "input.wav", directory / "proposal.wav"
            source.write_bytes(encode_wav(pcm))
            settings = SA3GenerationSettings(seconds=parameters["model_seconds"], seed=parameters["seed"],
                steps=parameters["steps"], threads=parameters["threads"], cfg=parameters["cfg"],
                negative_prompt=parameters["negative_prompt"], timeout_seconds=parameters["timeout_seconds"])
            command = build_sa3_command(runtime=runtime, prompt=parameters["prompt"], output=destination,
                                        settings=settings, seed=parameters["seed"])
            command.extend(["--init-audio", str(source), "--inpaint-range", parameters["inpaint_argument"]])
            environment = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
                "USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "COMSPEC", "PATHEXT", "LD_LIBRARY_PATH") if key in os.environ}
            environment.update(_OFFLINE_ENVIRONMENT)
            environment.update({"PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", "NO_COLOR": "1"})
            process = run_process(command, cwd=runtime.root, environment=environment,
                timeout_seconds=parameters["timeout_seconds"], audio_model=PROFILE, scratch=directory)
            raw = decode_wav(stable_read(destination))
            if (raw.sample_rate, raw.channels) != (pcm.sample_rate, pcm.channels) or raw.frames != parameters["model_seconds"] * RATE:
                raise AudioError("sa3_output_mismatch", "SA3 returned an unexpected format or frame count")
            aligned = trim(raw, 0, pcm.frames) if raw.frames != pcm.frames else raw
            output, report = splice(parameters["splice"], [pcm, aligned])
            if report["observed_changes"]["outside_changed_sample_count"]:
                raise AudioError("constraint_violation", "Final output changed outside its write window")
            return OperationOutput(output, {**report,
                **{key: parameters[key] for key in ("context_read", "requested_edit", "model_mask", "allowed_write")},
                "model_observed_changes": observed_changes(pcm, aligned, parameters["allowed_write"]),
                "output_adaptation": {"method": "pcm16-prefix-crop/v1", "raw_frames": raw.frames, "output_frames": pcm.frames,
                                      "resampled": False, "raw_format": raw.facts()},
                "backend_execution": process.report,
                "unverified_goals": ["Musical suitability and splice audibility require human listening."]},
                (AudioAttachment(raw, "model_proposal", {"selection": "unassembled model proposal; not the final edit"}),))

    def operation(self):
        try:
            _runtime(self.runtime_root)
            availability = "available"
        except AudioError:
            availability = "unavailable"
        return Operation("score.sa3_inpaint/v1", SCHEMA, self.resolve, self.execute, PROFILE,
            mapping=identity_mapping, writes=lambda p, pcm: p["allowed_write"], realization="model_with_pcm_assembly",
            availability=availability)


def registry(runtime_root=None):
    value = Registry()
    value.register(SA3EditAdapter(runtime_root).operation())
    return value
