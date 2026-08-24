from __future__ import annotations

import hashlib
import math
import struct
import wave
from pathlib import Path
from typing import Any

from .errors import BoundaryError, IntegrityError

PCM_WAV_MAX_BYTES = 64 * 1024 * 1024


def probe_pcm_wav(path: Path | str, *, max_bytes: int = PCM_WAV_MAX_BYTES) -> dict[str, Any]:
    candidate = Path(path)
    try:
        byte_count = candidate.stat().st_size
    except OSError as exc:
        raise IntegrityError(f"cannot stat WAV input: {candidate}: {exc}") from exc
    if byte_count <= 0 or byte_count > max_bytes:
        raise BoundaryError(
            f"WAV byte count must be between 1 and {max_bytes}: {byte_count}",
            code="audio_size_rejected",
        )
    if candidate.is_symlink():
        raise BoundaryError(f"WAV input cannot be a symlink: {candidate}", code="unsafe_audio_path")

    try:
        with wave.open(str(candidate), "rb") as reader:
            channels = reader.getnchannels()
            sample_width = reader.getsampwidth()
            sample_rate = reader.getframerate()
            frame_count = reader.getnframes()
            compression = reader.getcomptype()
            payload = reader.readframes(frame_count)
    except (OSError, EOFError, wave.Error) as exc:
        raise IntegrityError(f"invalid or unsupported WAV: {candidate}: {exc}") from exc

    if compression != "NONE" or sample_width != 2:
        raise BoundaryError(
            "M0 accepts only uncompressed signed-16-bit PCM WAV",
            code="audio_format_rejected",
        )
    if channels < 1 or channels > 8:
        raise BoundaryError(f"unsupported WAV channel count: {channels}")
    if sample_rate < 8000 or sample_rate > 192000:
        raise BoundaryError(f"unsupported WAV sample rate: {sample_rate}")
    if frame_count < 1 or frame_count > 230400000:
        raise BoundaryError(f"unsupported WAV frame count: {frame_count}")
    expected_payload = frame_count * channels * sample_width
    if len(payload) != expected_payload:
        raise IntegrityError(
            f"incomplete WAV frame payload: expected {expected_payload}, read {len(payload)}"
        )

    return {
        "container": "wav",
        "codec": "pcm_s16le",
        "sample_rate_hz": sample_rate,
        "channels": channels,
        "sample_width_bytes": sample_width,
        "frame_count": frame_count,
    }


def render_mock_sine_wav(
    path: Path,
    *,
    sample_rate_hz: int,
    channels: int,
    duration_samples: int,
    frequency_hz: float,
    amplitude: float,
    seed: int,
) -> None:
    if frequency_hz >= sample_rate_hz / 2:
        raise BoundaryError(
            f"mock frequency must be below Nyquist ({sample_rate_hz / 2:g} Hz)",
            code="mock_frequency_rejected",
        )
    estimated_bytes = 44 + duration_samples * channels * 2
    if estimated_bytes > PCM_WAV_MAX_BYTES:
        raise BoundaryError(
            f"mock WAV would exceed {PCM_WAV_MAX_BYTES} bytes",
            code="audio_size_rejected",
        )

    seed_bytes = seed.to_bytes(4, byteorder="big", signed=False)
    phase_fraction = int.from_bytes(hashlib.sha256(seed_bytes).digest()[:8], "big") / 2**64
    phase = phase_fraction * math.tau
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with wave.open(str(path), "wb") as writer:
            writer.setnchannels(channels)
            writer.setsampwidth(2)
            writer.setframerate(sample_rate_hz)
            frames_per_chunk = 4096
            for start in range(0, duration_samples, frames_per_chunk):
                count = min(frames_per_chunk, duration_samples - start)
                output = bytearray(count * channels * 2)
                offset = 0
                for frame_index in range(start, start + count):
                    value = int(
                        round(
                            math.sin(
                                phase + math.tau * frequency_hz * frame_index / sample_rate_hz
                            )
                            * amplitude
                            * 32767
                        )
                    )
                    packed = struct.pack("<h", value)
                    for _ in range(channels):
                        output[offset : offset + 2] = packed
                        offset += 2
                writer.writeframesraw(output)
    except (OSError, wave.Error) as exc:
        raise IntegrityError(f"failed to write deterministic mock WAV: {path}: {exc}") from exc
