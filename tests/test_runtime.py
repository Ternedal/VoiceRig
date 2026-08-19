import voicerig.runtime as runtime


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
    result = runtime.voice_build_readiness()
    assert result["ready"] is True
    assert any("VRAM" in item for item in result["warnings"])
