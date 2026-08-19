import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import voicerig.model_warmup as warmup


def test_warm_chatterbox_requires_danish_support(monkeypatch):
    class FakeModel:
        device = "cuda"
        sr = 24000

        @staticmethod
        def get_supported_languages():
            return {"da": "Danish", "en": "English"}

    monkeypatch.setattr(warmup, "_shared_model", lambda: FakeModel())
    report = warmup.warm_chatterbox()

    assert report["ok"] is True
    assert report["model"] == "v3"
    assert report["language"] == "da"
    assert report["device"] == "cuda"


def test_warm_chatterbox_fails_without_danish(monkeypatch):
    class FakeModel:
        @staticmethod
        def get_supported_languages():
            return {"en": "English"}

    monkeypatch.setattr(warmup, "_shared_model", lambda: FakeModel())
    with pytest.raises(RuntimeError, match="dansk V3"):
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
        payload = {"ok": True, "model": "pyannote/speaker-diarization-community-1", "telemetry": "0"}
        return SimpleNamespace(
            returncode=0,
            stdout="VOICERIG_DIARIZATION_READY=" + json.dumps(payload) + "\n",
            stderr="",
        )

    monkeypatch.setattr(warmup.subprocess, "run", fake_run)
    report = warmup.warm_diarization()

    assert captured["cmd"][-1] == "--preload"
    assert captured["env"]["PYANNOTE_METRICS_ENABLED"] == "0"
    assert report["ok"] is True
    assert report["telemetry"] == "0"


def test_warm_diarization_surfaces_actionable_model_access_error(tmp_path: Path, monkeypatch):
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(warmup, "_worker_python", lambda: python)
    monkeypatch.setattr(
        warmup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=3,
            stdout="",
            stderr="gated repository access denied",
        ),
    )

    with pytest.raises(RuntimeError, match="HF_TOKEN"):
        warmup.warm_diarization()
