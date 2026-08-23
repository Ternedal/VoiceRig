from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import voicerig.app.main as main


def test_voice_build_resets_and_returns_server_process_gpu_metrics(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    package = tmp_path / "metrics.mrvoice"
    package.write_bytes(b"package")
    reset = {"called": False}

    monkeypatch.setattr(main, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(main, "reset_cuda_peaks", lambda: reset.__setitem__("called", True) or True)
    monkeypatch.setattr(
        main,
        "cuda_memory_stats",
        lambda: {
            "available": True,
            "allocated_gb": 4.0,
            "reserved_gb": 5.0,
            "peak_allocated_gb": 8.0,
            "peak_reserved_gb": 9.0,
        },
    )
    monkeypatch.setattr(
        main,
        "create_voice",
        lambda *args, **kwargs: SimpleNamespace(
            package=package,
            reference=tmp_path / "reference.wav",
            diarization_used=True,
        ),
    )
    monkeypatch.setattr(
        main,
        "validate_package",
        lambda _package: {"id": "metrics-12345678", "name": "Metrics", "language": "da"},
    )

    response = TestClient(main.app).post(
        "/api/voices",
        data={"name": "Metrics", "language": "da", "install_in_modelrig": "false"},
        files={"files": ("voice.mp4", b"fake-media", "video/mp4")},
    )

    assert response.status_code == 200
    assert reset["called"] is True
    assert response.json()["gpu"]["peak_allocated_gb"] == 8.0
