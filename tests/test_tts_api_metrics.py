from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import voicerig.app.tts_api as tts_api
from voicerig.app.main import app


def test_tts_response_exposes_same_process_peak_vram(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    package = tmp_path / "voice.mrvoice"
    package.write_bytes(b"package")
    monkeypatch.setattr(tts_api, "resolve_package", lambda _name=None: package)

    def fake_synthesize(_package, _text, output):
        # The route only transports bytes here; WAV semantics are covered by
        # package-runtime/audio tests.
        output.write_bytes(b"RIFF" + b"x" * 64)
        return {
            "voice": "Anders",
            "voice_id": "anders-12345678",
            "package": "voice.mrvoice",
            "sample_rate": 24000,
            "duration": 1.0,
            "device": "cuda",
        }

    monkeypatch.setattr(tts_api, "synthesize", fake_synthesize)
    monkeypatch.setattr(
        tts_api,
        "cuda_memory_stats",
        lambda: {
            "available": True,
            "allocated_gb": 5.0,
            "reserved_gb": 6.0,
            "peak_allocated_gb": 8.5,
            "peak_reserved_gb": 9.25,
        },
    )

    response = TestClient(app).post(
        "/api/tts/synthesize",
        json={"text": "Hej", "voice_package": "voice.mrvoice"},
    )

    assert response.status_code == 200
    assert response.headers["X-VoiceRig-Device"] == "cuda"
    assert response.headers["X-VoiceRig-Package"] == "voice.mrvoice"
    assert response.headers["X-VoiceRig-Peak-Allocated-GB"] == "8.5"
    assert response.headers["X-VoiceRig-Peak-Reserved-GB"] == "9.25"
