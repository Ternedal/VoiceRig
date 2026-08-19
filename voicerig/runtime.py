from __future__ import annotations

import os
from pathlib import Path


def _device_setting(name: str, default: str) -> str:
    value = os.getenv(name, default).strip().lower()
    if value not in {"auto", "cpu", "cuda"}:
        return default
    return value


def chatterbox_device() -> str:
    requested = _device_setting("VOICERIG_CHATTERBOX_DEVICE", "auto")
    if requested == "cpu":
        return "cpu"
    try:
        import torch
    except Exception:
        return "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("VOICERIG_CHATTERBOX_DEVICE=cuda, men CUDA er ikke tilgængelig.")
    return "cuda" if torch.cuda.is_available() else "cpu"


def diarization_device() -> str:
    """Diarization is intentionally isolated in a CPU-only venv/process."""
    return "cpu"


def _diarization_runtime_present() -> bool:
    explicit = os.getenv("VOICERIG_DIARIZATION_PYTHON", "").strip()
    if explicit:
        return Path(explicit).expanduser().is_file()
    root = Path(__file__).resolve().parents[1]
    return any(
        p.is_file()
        for p in (
            root / ".venv-diarization" / "Scripts" / "python.exe",
            root / ".venv-diarization" / "bin" / "python",
        )
    )


def hardware_status() -> dict:
    status = {
        "chatterbox_device": "cpu",
        "diarization_device": "cpu",
        "diarization_runtime": "separate",
        "diarization_available": _diarization_runtime_present(),
        "cuda_available": False,
        "gpu": None,
        "vram_total_gb": None,
        "vram_free_gb": None,
    }
    try:
        import torch
    except Exception:
        return status

    status["cuda_available"] = bool(torch.cuda.is_available())
    if torch.cuda.is_available():
        props = torch.cuda.get_device_properties(0)
        status["gpu"] = props.name
        status["vram_total_gb"] = round(props.total_memory / (1024 ** 3), 1)
        try:
            free, _total = torch.cuda.mem_get_info()
            status["vram_free_gb"] = round(free / (1024 ** 3), 1)
        except Exception:
            pass
    try:
        status["chatterbox_device"] = chatterbox_device()
    except RuntimeError as exc:
        status["configuration_error"] = str(exc)
    return status
