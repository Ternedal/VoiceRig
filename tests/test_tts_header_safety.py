from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from fastapi.testclient import TestClient

import voicerig.app.main as main
import voicerig.app.tts_api as tts_api


def test_ascii_header_roundtrips_danish_text():
    raw = "Søren Æblegrød æøå"
    encoded = tts_api._ascii_header(raw)

    assert all(ord(ch) < 128 for ch in encoded)
    assert unquote(encoded) == raw


def test_standard_tts_endpoint_handles_danish_voice_and_package_names(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    package = tmp_path / "søren-stemme.mrvoice"
    package.write_bytes(b"package")

    monkeypatch.setattr(tts_api, "resolve_package", lambda voice_package: package)
    monkeypatch.setattr(tts_api, "cuda_memory_stats", lambda: {"available": False})

    def fake_synthesize(source, text, output):
        output.write_bytes(b"RIFF-test-output")
        return {
            "voice_id": "søren-æøå",
            "voice": "Søren Æblegrød",
            "package": "søren-stemme.mrvoice",
            "sample_rate": 24000,
            "duration": 1.0,
            "device": "cuda",
        }

    monkeypatch.setattr(tts_api, "synthesize", fake_synthesize)

    response = TestClient(main.app).post(
        "/api/tts/synthesize",
        json={"text": "Hej", "voice_package": package.name},
    )

    assert response.status_code == 200
    assert response.content == b"RIFF-test-output"
    assert unquote(response.headers["X-VoiceRig-Voice"]) == "Søren Æblegrød"
    assert unquote(response.headers["X-VoiceRig-Voice-ID"]) == "søren-æøå"
    assert unquote(response.headers["X-VoiceRig-Package"]) == "søren-stemme.mrvoice"
    assert all(
        all(ord(ch) < 128 for ch in response.headers[name])
        for name in ("X-VoiceRig-Voice", "X-VoiceRig-Voice-ID", "X-VoiceRig-Package")
    )
