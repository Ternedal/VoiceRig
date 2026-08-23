from __future__ import annotations

import json
import wave
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import voicerig.app.main as app_main
import voicerig.app.tts_api as tts_api
import voicerig.engines.omnivoice as omnivoice
from voicerig.model_contract import (
    OMNIVOICE_ASR_REVISION,
    OMNIVOICE_MODEL_REVISION,
    OMNIVOICE_SOURCE_REVISION,
)
from voicerig.profiles.package import build_package


def _wav(path: Path, frames: int = 2400, sample_rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(b"\x00\x00" * frames)


def _package(tmp_path: Path, language: str = "da") -> Path:
    reference = tmp_path / "reference.wav"
    conditioning = tmp_path / "conditioning.pt"
    preview = tmp_path / "preview.wav"
    _wav(reference)
    conditioning.write_bytes(b"conditioning")
    _wav(preview)
    package = tmp_path / "voice.mrvoice"
    return build_package("Test", language, reference, conditioning, preview, package)


def _client(monkeypatch) -> TestClient:
    # Starlette TestClient reports a synthetic peer named "testclient" rather
    # than 127.0.0.1. Bypass only the network boundary in these endpoint unit
    # tests; dedicated netguard tests keep the production loopback gate locked.
    monkeypatch.setattr(app_main, "allow_lan", lambda: True)
    return TestClient(app_main.app)


def test_omnivoice_worker_runs_after_chatterbox_release_and_strips_hf_token(
    tmp_path: Path, monkeypatch
):
    reference = tmp_path / "reference.wav"
    output = tmp_path / "output.wav"
    _wav(reference)
    fake_python = tmp_path / "python.exe"
    fake_python.write_bytes(b"")
    events: list[str] = []
    captured_env = {}

    monkeypatch.setattr(omnivoice, "ensure_runtime", lambda: fake_python)
    monkeypatch.setattr(omnivoice, "release_shared_model", lambda: events.append("release"))
    monkeypatch.setenv("HF_TOKEN", "must-not-leak")
    monkeypatch.setenv("HUGGING_FACE_HUB_TOKEN", "must-not-leak-either")

    def fake_run(command, **kwargs):
        events.append("worker")
        captured_env.update(kwargs["env"])
        out = Path(command[command.index("--output") + 1])
        _wav(out, frames=4800)
        result = {
            "engine": "OmniVoice",
            "model": "k2-fsa/OmniVoice",
            "model_revision": OMNIVOICE_MODEL_REVISION,
            "source_revision": OMNIVOICE_SOURCE_REVISION,
            "sample_rate": 24000,
            "duration": 0.2,
            "language": "da",
        }
        return SimpleNamespace(
            returncode=0,
            stdout=omnivoice._RESULT_MARKER + json.dumps(result) + "\n",
            stderr="",
        )

    monkeypatch.setattr(omnivoice.subprocess, "run", fake_run)
    result = omnivoice.synthesize_omnivoice_danish(reference, "Hej verden", output)

    assert events == ["release", "worker"]
    assert "HF_TOKEN" not in captured_env
    assert "HUGGING_FACE_HUB_TOKEN" not in captured_env
    assert captured_env["HF_HUB_DISABLE_TELEMETRY"] == "1"
    assert output.is_file()
    assert result["model_revision"] == OMNIVOICE_MODEL_REVISION


def test_omnivoice_contract_uses_immutable_source_model_and_asr_revisions():
    assert len(OMNIVOICE_SOURCE_REVISION) == 40
    assert len(OMNIVOICE_MODEL_REVISION) == 40
    assert len(OMNIVOICE_ASR_REVISION) == 40
    assert OMNIVOICE_SOURCE_REVISION != OMNIVOICE_MODEL_REVISION


def test_omnivoice_compare_api_uses_same_profile_reference(tmp_path: Path, monkeypatch):
    package = _package(tmp_path, "da")
    observed = {}

    monkeypatch.setattr(tts_api, "resolve_package", lambda _name=None: package)

    def fake_synthesize(reference: Path, text: str, output: Path):
        observed["reference"] = reference.read_bytes()
        observed["text"] = text
        _wav(output, frames=7200)
        return {
            "engine": "OmniVoice",
            "model": "k2-fsa/OmniVoice",
            "model_revision": OMNIVOICE_MODEL_REVISION,
            "source_revision": OMNIVOICE_SOURCE_REVISION,
            "sample_rate": 24000,
            "duration": 0.3,
            "language": "da",
        }

    monkeypatch.setattr(tts_api, "synthesize_omnivoice_danish", fake_synthesize)
    client = _client(monkeypatch)
    response = client.post(
        "/api/tts/compare/omnivoice",
        json={"text": "Rødgrød med fløde", "voice_package": package.name},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["X-VoiceRig-Engine"] == "OmniVoice"
    assert response.headers["X-VoiceRig-Revision"] == OMNIVOICE_MODEL_REVISION
    assert response.headers["X-VoiceRig-Source-Revision"] == OMNIVOICE_SOURCE_REVISION
    assert observed["text"] == "Rødgrød med fløde"
    assert observed["reference"] == (tmp_path / "reference.wav").read_bytes()


def test_omnivoice_compare_api_rejects_non_danish_profile(tmp_path: Path, monkeypatch):
    package = _package(tmp_path, "en")
    monkeypatch.setattr(tts_api, "resolve_package", lambda _name=None: package)
    called = False

    def should_not_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("OmniVoice must not run for non-Danish comparison")

    monkeypatch.setattr(tts_api, "synthesize_omnivoice_danish", should_not_run)
    client = _client(monkeypatch)
    response = client.post(
        "/api/tts/compare/omnivoice",
        json={"text": "Hello", "voice_package": package.name},
    )

    assert response.status_code == 422
    assert "kun til danske profiler" in response.json()["detail"]
    assert called is False
