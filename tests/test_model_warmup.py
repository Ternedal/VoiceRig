import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import voicerig.model_warmup as warmup
from voicerig.model_contract import (
    CHATTERBOX_ENGINE,
    CHATTERBOX_MODEL,
    CHATTERBOX_SOURCE_REVISION,
    MODEL_READINESS_SCHEMA,
    PYANNOTE_MODEL_ID,
    PYANNOTE_PACKAGE_VERSION,
)


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
    assert report["model"] == CHATTERBOX_MODEL
    assert report["revision"] == CHATTERBOX_SOURCE_REVISION
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
        payload = {
            "ok": True,
            "model": PYANNOTE_MODEL_ID,
            "package_version": PYANNOTE_PACKAGE_VERSION,
            "telemetry": "0",
        }
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
    assert report["package_version"] == PYANNOTE_PACKAGE_VERSION
    assert report["telemetry"] == "0"


def test_warm_diarization_rejects_unverified_package_version(tmp_path: Path, monkeypatch):
    python = tmp_path / "python.exe"
    python.write_bytes(b"")
    monkeypatch.setattr(warmup, "_worker_python", lambda: python)
    payload = {
        "ok": True,
        "model": PYANNOTE_MODEL_ID,
        "package_version": "4.9.9",
        "telemetry": "0",
    }
    monkeypatch.setattr(
        warmup.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="VOICERIG_DIARIZATION_READY=" + json.dumps(payload) + "\n",
            stderr="",
        ),
    )

    with pytest.raises(RuntimeError, match="package-version"):
        warmup.warm_diarization()


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


def test_readiness_marker_records_exact_model_contract(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(warmup, "data_dir", lambda: tmp_path)
    report = {
        "ok": True,
        "chatterbox": {"ok": True},
        "diarization": {"ok": True},
    }

    marker = warmup._write_readiness_marker(report)
    payload = json.loads(marker.read_text(encoding="utf-8"))

    assert payload["schema"] == MODEL_READINESS_SCHEMA
    assert payload["chatterbox"] == {
        "engine": CHATTERBOX_ENGINE,
        "model": CHATTERBOX_MODEL,
        "revision": CHATTERBOX_SOURCE_REVISION,
    }
    assert payload["diarization"] == {
        "package_version": PYANNOTE_PACKAGE_VERSION,
        "model": PYANNOTE_MODEL_ID,
    }
    assert payload["warmup"] == report
