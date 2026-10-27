"""Offline static SA3 checks, independent of model imports and device probes."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .authoring import DEFAULT_RUNTIME_ROOT


def doctor_provider():
    from matter_audio_core.diagnostics import backend_report, check
    from .sa3_edit import COMPONENTS

    checks = []
    explicit = bool(os.environ.get("SCORE_MATTER_SA3_ROOT"))
    configured = explicit
    try:
        root = Path(os.environ.get("SCORE_MATTER_SA3_ROOT") or DEFAULT_RUNTIME_ROOT).expanduser().resolve(strict=False)
        configured = explicit or root.is_dir()
        python = next((path for path in (root / ".venv/Scripts/python.exe", root / ".venv/bin/python") if path.is_file()), None)
        identity = hashlib.sha256("\0".join((str(root), str(python) if python else "",
                                             str(root / "scripts/sa3_tflite.py"))).encode("utf-8")).hexdigest()
        checks.append(check("sa3_configuration", "configuration", "ok", "configuration_resolved",
                            "SA3 configuration was resolved locally.",
                            details={"configuration_id": identity, "explicit_configuration": explicit}))
        checks.append(check("sa3_python", "file", "ok" if python else "error",
                            "runtime_python_present" if python else "runtime_python_missing",
                            "SA3 runtime Python is present; it was not executed." if python else "SA3 runtime Python is missing.",
                            remedy=None if python else "Configure an existing SA3 runtime; doctor does not install one."))
        sizes = [(root / name).stat().st_size if (root / name).is_file() else None for name in COMPONENTS]
        missing, empty = sizes.count(None), sizes.count(0)
        ready = not (missing or empty)
        checks.append(check("sa3_components", "file", "ok" if ready else "error",
                            "components_present" if ready else "components_incomplete",
                            "Required model files are present and nonempty; weights were not loaded or hashed." if ready
                            else "Required SA3 generation or inpaint files are missing or empty.",
                            remedy=None if ready else "Complete the configured runtime outside doctor, including the SAME-L encoder.",
                            details={"component_count": len(COMPONENTS), "missing_count": missing, "empty_count": empty}))
        script = root / "scripts/sa3_tflite.py"
        try:
            with script.open("rb") as stream:
                raw = stream.read(256 * 1024 + 1)
            if len(raw) > 256 * 1024:
                raise ValueError("bounded_driver_read")
            driver = "".join(raw.decode("utf-8").split())
            required = ("SAMPLE_RATE=44100", "SAMPLES_PER_LATENT=4096",
                        "int(round(inp_start_sec*SAMPLE_RATE/SAMPLES_PER_LATENT))",
                        "int(round(inp_end_sec*SAMPLE_RATE/SAMPLES_PER_LATENT))",
                        "int(np.ceil(seconds*SAMPLE_RATE/SAMPLES_PER_LATENT))")
            supported = all(marker in driver for marker in required)
            checks.append(check("sa3_driver", "file", "ok" if supported else "error",
                                "driver_profile_supported" if supported else "driver_profile_unsupported",
                                "The readable driver matches the reviewed inpaint time-coordinate markers." if supported
                                else "The driver does not match the reviewed inpaint time-coordinate profile.",
                                remedy=None if supported else "Review the driver profile before enabling SA3 inpainting.",
                                details={"driver_profile_supported": supported, "driver_digest": hashlib.sha256(raw).hexdigest()}))
        except (OSError, UnicodeError, ValueError):
            checks.append(check("sa3_driver", "file", "error", "driver_unreadable",
                                "SA3 driver is missing, unreadable, invalid UTF-8 or exceeds the diagnostic read limit.",
                                remedy="Check the configured driver locally; doctor never runs or repairs it."))
    except (OSError, ValueError, RuntimeError):
        checks.append(check("sa3_filesystem", "file", "error", "configuration_unreadable",
                            "SA3 configuration or file metadata could not be read.",
                            remedy="Check local runtime configuration and file permissions."))
    checks.append(check("sa3_device", "device", "unknown", "device_not_probed",
                        "No model or runtime Python was loaded; execution device and inference success are unknown."))
    return [backend_report("score_sa3", configured=configured, checks=checks, optional=True)]
