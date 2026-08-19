from __future__ import annotations

import json
import os
from pathlib import Path

from voicerig.config import data_dir
from voicerig.model_contract import (
    CHATTERBOX_ENGINE,
    CHATTERBOX_MODEL,
    CHATTERBOX_SOURCE_REVISION,
    DIARIZATION_TORCH_VERSION,
    DIARIZATION_TORCHAUDIO_VERSION,
    DIARIZATION_TORCHCODEC_VERSION,
    MODEL_READINESS_SCHEMA,
    PYANNOTE_MODEL_ID,
    PYANNOTE_PACKAGE_VERSION,
)

# A 12 GB consumer GPU usually exposes slightly less than the marketing number
# after unit conversion/runtime reservation. Treat >=11 GiB as the intended
# "12 GB class" target rather than rejecting valid RTX 3060-class cards.
_TARGET_VRAM_GB = 11.0


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


def model_warmup_status() -> dict:
    marker = data_dir() / "model-readiness.json"
    if not marker.is_file():
        return {
            "verified": False,
            "marker": str(marker),
            "detail": "Modellerne er ikke forhåndsverificeret. Kør setup-windows.ps1 igen.",
        }
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "verified": False,
            "marker": str(marker),
            "detail": "Model-readiness-filen er beskadiget. Kør setup-windows.ps1 igen.",
        }
    diarization = payload.get("diarization") or {}
    expected = (
        payload.get("schema") == MODEL_READINESS_SCHEMA
        and (payload.get("chatterbox") or {}).get("engine") == CHATTERBOX_ENGINE
        and (payload.get("chatterbox") or {}).get("model") == CHATTERBOX_MODEL
        and (payload.get("chatterbox") or {}).get("revision") == CHATTERBOX_SOURCE_REVISION
        and diarization.get("package_version") == PYANNOTE_PACKAGE_VERSION
        and diarization.get("model") == PYANNOTE_MODEL_ID
        and diarization.get("torch_version") == DIARIZATION_TORCH_VERSION
        and diarization.get("torchaudio_version") == DIARIZATION_TORCHAUDIO_VERSION
        and diarization.get("torchcodec_version") == DIARIZATION_TORCHCODEC_VERSION
    )
    if not expected:
        return {
            "verified": False,
            "marker": str(marker),
            "detail": "Den verificerede modelcache matcher ikke denne VoiceRig-version. Kør setup-windows.ps1 igen.",
        }
    return {
        "verified": True,
        "marker": str(marker),
        "verified_at": payload.get("verified_at"),
        "chatterbox": payload.get("chatterbox"),
        "diarization": diarization,
        "detail": None,
    }


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
        "target_vram_gb": _TARGET_VRAM_GB,
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


def reset_cuda_peaks() -> bool:
    """Reset peak VRAM counters in the VoiceRig process that owns Chatterbox."""
    try:
        import torch
    except Exception:
        return False
    if not torch.cuda.is_available():
        return False
    try:
        torch.cuda.reset_peak_memory_stats()
    except Exception:
        return False
    return True


def cuda_memory_stats() -> dict:
    """Report current/peak CUDA memory for physical 12 GB acceptance evidence."""
    empty = {
        "available": False,
        "allocated_gb": None,
        "reserved_gb": None,
        "peak_allocated_gb": None,
        "peak_reserved_gb": None,
    }
    try:
        import torch
    except Exception:
        return empty
    if not torch.cuda.is_available():
        return empty
    gib = 1024 ** 3
    try:
        return {
            "available": True,
            "allocated_gb": round(torch.cuda.memory_allocated() / gib, 3),
            "reserved_gb": round(torch.cuda.memory_reserved() / gib, 3),
            "peak_allocated_gb": round(torch.cuda.max_memory_allocated() / gib, 3),
            "peak_reserved_gb": round(torch.cuda.max_memory_reserved() / gib, 3),
        }
    except Exception:
        return empty


def voice_build_readiness() -> dict:
    """Return a human-readable preflight verdict without loading ML models.

    Service health and ML readiness are deliberately separate: VoiceRig may be
    up and able to serve/download existing packages even while CUDA, the
    isolated diarization environment, or the preloaded model cache needs setup.
    """
    hw = hardware_status()
    models = model_warmup_status()
    blockers: list[str] = []
    warnings: list[str] = []

    if hw.get("configuration_error"):
        blockers.append(str(hw["configuration_error"]))
    elif hw.get("chatterbox_device") != "cuda":
        blockers.append("Chatterbox er ikke klar på CUDA.")

    total = hw.get("vram_total_gb")
    if isinstance(total, (int, float)):
        if total < _TARGET_VRAM_GB:
            blockers.append(
                f"GPU'en har {total:.1f} GB VRAM; VoiceRig v1 målretter 12 GB-klassen (>= {_TARGET_VRAM_GB:.0f} GiB registreret)."
            )
        free = hw.get("vram_free_gb")
        if isinstance(free, (int, float)) and free < 6.0:
            warnings.append(
                f"Kun {free:.1f} GB VRAM er fri lige nu; luk andre GPU-tunge modeller før voice-build hvis CUDA løber tør."
            )
    elif hw.get("cuda_available"):
        warnings.append("CUDA er fundet, men VRAM-størrelsen kunne ikke aflæses.")

    if not hw.get("diarization_available"):
        blockers.append("Den separate CPU-runtime til speaker-analyse er ikke installeret.")
    if not models.get("verified"):
        blockers.append(str(models.get("detail") or "VoiceRig-modellerne er ikke verificeret."))

    return {
        "ready": not blockers,
        "profile": "single-nvidia-gpu-12gb-class",
        "hardware": hw,
        "models": models,
        "blockers": blockers,
        "warnings": warnings,
    }
