import json

import voicerig.runtime as runtime
from voicerig.model_contract import (
    CHATTERBOX_ENGINE,
    CHATTERBOX_MODEL,
    CHATTERBOX_SOURCE_REVISION,
    MODEL_READINESS_SCHEMA,
    PYANNOTE_MODEL_ID,
)


def _verified_models():
    return {"verified": True, "detail": None}


def test_diarization_defaults_to_cpu(monkeypatch):
    monkeypatch.delenv("VOICERIG_DIARIZATION_DEVICE", raising=False)
    assert runtime.diarization_device() == "cpu"


def test_invalid_device_setting_falls_back(monkeypatch):
    monkeypatch.setenv("VOICERIG_DIARIZATION_DEVICE", "potato")
    assert runtime.diarization_device() == "cpu"


def test_12gb_cuda_profile_is_ready(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "hardware_status",
        lambda: {
            "chatterbox_device": "cuda",
            "diarization_device": "cpu",
            "diarization_runtime": "separate",
            "diarization_available": True,
            "cuda_available": True,
            "gpu": "NVIDIA GeForce RTX 3060",
            "vram_total_gb": 12.0,
            "vram_free_gb": 8.0,
            "target_vram_gb": 11.0,
        },
    )
    monkeypatch.setattr(runtime, "model_warmup_status", _verified_models)
    result = runtime.voice_build_readiness()
    assert result["ready"] is True
    assert result["blockers"] == []
    assert result["profile"] == "single-nvidia-gpu-12gb-class"


def test_below_target_vram_is_reported(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "hardware_status",
        lambda: {
            "chatterbox_device": "cuda",
            "diarization_available": True,
            "cuda_available": True,
            "gpu": "small gpu",
            "vram_total_gb": 8.0,
            "vram_free_gb": 7.0,
        },
    )
    monkeypatch.setattr(runtime, "model_warmup_status", _verified_models)
    result = runtime.voice_build_readiness()
    assert result["ready"] is False
    assert any("VRAM" in item for item in result["blockers"])


def test_low_free_vram_warns_without_failing_profile(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "hardware_status",
        lambda: {
            "chatterbox_device": "cuda",
            "diarization_available": True,
            "cuda_available": True,
            "gpu": "NVIDIA GeForce RTX 3060",
            "vram_total_gb": 12.0,
            "vram_free_gb": 4.0,
        },
    )
    monkeypatch.setattr(runtime, "model_warmup_status", _verified_models)
    result = runtime.voice_build_readiness()
    assert result["ready"] is True
    assert any("VRAM" in item for item in result["warnings"])


def test_unverified_models_block_voice_creation(monkeypatch):
    monkeypatch.setattr(
        runtime,
        "hardware_status",
        lambda: {
            "chatterbox_device": "cuda",
            "diarization_available": True,
            "cuda_available": True,
            "gpu": "NVIDIA GeForce RTX 3060",
            "vram_total_gb": 12.0,
            "vram_free_gb": 8.0,
        },
    )
    monkeypatch.setattr(
        runtime,
        "model_warmup_status",
        lambda: {"verified": False, "detail": "Kør setup-windows.ps1 igen."},
    )
    result = runtime.voice_build_readiness()
    assert result["ready"] is False
    assert any("setup-windows" in item for item in result["blockers"])


def test_model_readiness_marker_must_match_current_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "data_dir", lambda: tmp_path)
    marker = tmp_path / "model-readiness.json"
    marker.write_text(
        json.dumps(
            {
                "schema": MODEL_READINESS_SCHEMA,
                "verified_at": "2026-08-19T00:00:00+00:00",
                "chatterbox": {
                    "engine": CHATTERBOX_ENGINE,
                    "model": CHATTERBOX_MODEL,
                    "revision": CHATTERBOX_SOURCE_REVISION,
                },
                "diarization": {"model": PYANNOTE_MODEL_ID},
            }
        ),
        encoding="utf-8",
    )
    assert runtime.model_warmup_status()["verified"] is True

    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload["chatterbox"]["revision"] = "0" * 40
    marker.write_text(json.dumps(payload), encoding="utf-8")
    stale = runtime.model_warmup_status()
    assert stale["verified"] is False
    assert "matcher ikke" in stale["detail"]
