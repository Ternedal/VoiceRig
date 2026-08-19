from __future__ import annotations

import os


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
    requested = _device_setting("VOICERIG_DIARIZATION_DEVICE", "cpu")
    if requested == "cpu":
        return "cpu"
    try:
        import torch
    except Exception:
        return "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("VOICERIG_DIARIZATION_DEVICE=cuda, men CUDA er ikke tilgængelig.")
    return "cuda" if torch.cuda.is_available() else "cpu"


def hardware_status() -> dict:
    status = {
        "chatterbox_device": "cpu",
        "diarization_device": "cpu",
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
        status["diarization_device"] = diarization_device()
    except RuntimeError as exc:
        status["configuration_error"] = str(exc)
    return status
