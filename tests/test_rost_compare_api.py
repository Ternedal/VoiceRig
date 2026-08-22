from __future__ import annotations

import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

import voicerig.app.main as main
import voicerig.app.tts_api as tts_api
from voicerig.model_contract import ROST_DANISH_MODEL, ROST_DANISH_REVISION


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "voice.mrvoice"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("reference.wav", b"RIFF-private-reference")
    return package


def test_rost_compare_uses_private_package_reference_without_mutating_profile(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    package = _package(tmp_path)
    captured = {}

    monkeypatch.setattr(tts_api, "resolve_package", lambda voice_package: package)
    monkeypatch.setattr(
        tts_api,
        "validate_package",
        lambda path: {"id": "voice-1", "name": "Dansk", "language": "da", "engine": {}},
    )

    def fake_rost(reference, text, output):
        captured["reference"] = reference.read_bytes()
        captured["text"] = text
        captured["output_parent"] = output.parent
        output.write_bytes(b"RIFF-rost-output")
        return {
            "engine": "Røst v3 Chatterbox 500M",
            "model": ROST_DANISH_MODEL,
            "revision": ROST_DANISH_REVISION,
            "sample_rate": 24000,
            "duration": 1.25,
            "language": "da",
        }

    monkeypatch.setattr(tts_api, "synthesize_rost_danish", fake_rost)
    before = package.read_bytes()

    response = TestClient(main.app).post(
        "/api/tts/compare/rost",
        json={"text": "Rødgrød med fløde.", "voice_package": package.name},
    )

    assert response.status_code == 200
    assert response.content == b"RIFF-rost-output"
    assert response.headers["X-VoiceRig-Engine"] == "Roest v3 Chatterbox 500M"
    assert response.headers["X-VoiceRig-Model"] == ROST_DANISH_MODEL
    assert response.headers["X-VoiceRig-Revision"] == ROST_DANISH_REVISION
    assert response.headers["X-VoiceRig-Language"] == "da"
    assert all(ord(ch) < 128 for ch in response.headers["X-VoiceRig-Engine"])
    assert captured["reference"] == b"RIFF-private-reference"
    assert captured["text"] == "Rødgrød med fløde."
    assert package.read_bytes() == before


def test_rost_compare_rejects_non_danish_profile(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    package = _package(tmp_path)
    monkeypatch.setattr(tts_api, "resolve_package", lambda voice_package: package)
    monkeypatch.setattr(
        tts_api,
        "validate_package",
        lambda path: {"id": "voice-1", "name": "English", "language": "en", "engine": {}},
    )

    response = TestClient(main.app).post(
        "/api/tts/compare/rost",
        json={"text": "Hello", "voice_package": package.name},
    )

    assert response.status_code == 422
    assert "kun til danske profiler" in response.json()["detail"]
