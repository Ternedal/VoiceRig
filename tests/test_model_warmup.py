import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import voicerig.model_warmup as warmup
from voicerig.engines.catalog import CURRENT_ENGINE
from voicerig.model_contract import (
    DIARIZATION_AUDIO_INPUT,
    DIARIZATION_TORCH_VERSION,
    DIARIZATION_TORCHAUDIO_VERSION,
    DIARIZATION_TORCHCODEC_VERSION,
    MODEL_READINESS_SCHEMA,
    PYANNOTE_MODEL_ID,
    PYANNOTE_PACKAGE_VERSION,
)


def _diarization_payload(**overrides):
    value = {
        "ok": True,
        "model": PYANNOTE_MODEL_ID,
        "package_version": PYANNOTE_PACKAGE_VERSION,
        "torch_version": DIARIZATION_TORCH_VERSION + "+cpu",
        "torchaudio_version": DIARIZATION_TORCHAUDIO_VERSION + "+cpu",
        "torchcodec_version": DIARIZATION_TORCHCODEC_VERSION,
        "cuda_available": False,
        "audio_input": DIARIZATION_AUDIO_INPUT,
        "telemetry": "0",
    }
    value.update(overrides)
    return value


def test_warm_chatterbox_requires_danish_support(monkeypatch):
    class FakeModel:
        device = "cuda"
        sr = 24000

        @staticmethod
        def get_supported_languages():
            return {"da": "Danish", "en": "English"}

    captured = {}

    def fake_shared(model, revision):
        captured["identity"] = (model, revision)
        return FakeModel()

    monkeypatch.setattr(warmup, "_shared_model", fake_shared)
    report = warmup.warm_chatterbox()
    assert captured["identity"] == (CURRENT_ENGINE.model, CURRENT_ENGINE.revision)
    assert report["ok"] is True
    assert report["engine"] == CURRENT_ENGINE.name
    assert report["model"] == CURRENT_ENGINE.model
    assert report["revision"] == CURRENT_ENGINE.revision
    assert report["language"] == "da"
    assert report["device"] == "cuda"


def test_warm_chatterbox_fails_without_danish(monkeypatch):
    class FakeModel:
        @staticmethod
        def get_supported_languages():
            return {"en": "English"}

    monkeypatch.setattr(warmup, "_shared_model", lambda *_args: FakeModel())
    with pytest.raises(RuntimeError, match="understøtter ikke dansk"):
        warmup.warm_chatterbox()


def test_warm_diarization_uses_preload_protocol_and_privacy_default(tmp_path: Path, monkeypatch):
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(warmup, "_worker_python", lambda: python)
    monkeypatch.delenv("PYANNOTE_METRICS_ENABLED", raising=False)
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="VOICERIG_DIARIZATION_READY=" + json.dumps(_diarization_payload()) + "\n", stderr="")

    monkeypatch.setattr(warmup.subprocess, "run", fake_run)
    report = warmup.warm_diarization()
    assert captured["cmd"][-1] == "--preload"
    assert captured["env"]["PYANNOTE_METRICS_ENABLED"] == "0"
    assert report["audio_input"] == DIARIZATION_AUDIO_INPUT
    assert report["telemetry"] == "0"


def test_warm_diarization_rejects_unverified_audio_input(tmp_path: Path, monkeypatch):
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(warmup, "_worker_python", lambda: python)
    monkeypatch.setattr(
        warmup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="VOICERIG_DIARIZATION_READY=" + json.dumps(_diarization_payload(audio_input="torchcodec-file")) + "\n", stderr=""),
    )
    with pytest.raises(RuntimeError, match="audio-input"):
        warmup.warm_diarization()


def test_warm_diarization_rejects_wrong_torchcodec_generation(tmp_path: Path, monkeypatch):
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(warmup, "_worker_python", lambda: python)
    monkeypatch.setattr(
        warmup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="VOICERIG_DIARIZATION_READY=" + json.dumps(_diarization_payload(torchcodec_version="0.13.0")) + "\n", stderr=""),
    )
    with pytest.raises(RuntimeError, match="uventet CPU-runtime"):
        warmup.warm_diarization()


def test_warm_diarization_surfaces_actionable_model_access_error(tmp_path: Path, monkeypatch):
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(warmup, "_worker_python", lambda: python)
    monkeypatch.setattr(
        warmup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=3, stdout="", stderr="gated repository access denied"),
    )
    with pytest.raises(RuntimeError, match="HF_TOKEN"):
        warmup.warm_diarization()


def test_readiness_marker_records_exact_model_contract(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(warmup, "data_dir", lambda: tmp_path)
    report = {"ok": True, "chatterbox": {"ok": True}, "diarization": _diarization_payload()}
    marker = warmup._write_readiness_marker(report)
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["schema"] == MODEL_READINESS_SCHEMA
    assert payload["chatterbox"] == {
        "engine": CURRENT_ENGINE.name,
        "model": CURRENT_ENGINE.model,
        "revision": CURRENT_ENGINE.revision,
    }
    assert payload["diarization"] == {
        "package_version": PYANNOTE_PACKAGE_VERSION,
        "model": PYANNOTE_MODEL_ID,
        "torch_version": DIARIZATION_TORCH_VERSION,
        "torchaudio_version": DIARIZATION_TORCHAUDIO_VERSION,
        "torchcodec_version": DIARIZATION_TORCHCODEC_VERSION,
        "audio_input": DIARIZATION_AUDIO_INPUT,
    }
