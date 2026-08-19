from __future__ import annotations

import voicerig.rig_validation as rv


def test_preflight_collects_runtime_blockers(monkeypatch):
    monkeypatch.setattr(
        rv,
        "voice_build_readiness",
        lambda: {
            "ready": False,
            "hardware": {"gpu": "Test GPU"},
            "blockers": ["CUDA mangler"],
            "warnings": ["lav fri VRAM"],
        },
    )
    monkeypatch.setattr(rv.shutil, "which", lambda name: None if name == "ffmpeg" else "/bin/git")
    monkeypatch.setattr(rv, "_module_available", lambda name: name == "torchaudio")
    monkeypatch.setattr(
        rv,
        "_probe_diarization_runtime",
        lambda: {"ok": False, "python": "python", "detail": "pyannote missing"},
    )

    report = rv.preflight()

    assert report["ok"] is False
    assert "CUDA mangler" in report["blockers"]
    assert "FFmpeg blev ikke fundet på PATH." in report["blockers"]
    assert "chatterbox-tts er ikke installeret i hovedmiljøet." in report["blockers"]
    assert any("pyannote CPU-runtime" in item for item in report["blockers"])
    assert report["warnings"] == ["lav fri VRAM"]


def test_preflight_passes_when_all_dependencies_are_ready(monkeypatch):
    monkeypatch.setattr(
        rv,
        "voice_build_readiness",
        lambda: {
            "ready": True,
            "hardware": {"gpu": "RTX 3060", "vram_total_gb": 12.0},
            "blockers": [],
            "warnings": [],
        },
    )
    monkeypatch.setattr(rv.shutil, "which", lambda _name: "/available")
    monkeypatch.setattr(rv, "_module_available", lambda _name: True)
    monkeypatch.setattr(
        rv,
        "_probe_diarization_runtime",
        lambda: {"ok": True, "python": "python", "detail": "4.0.7\n2.8.0+cpu"},
    )

    report = rv.preflight()

    assert report["ok"] is True
    assert report["blockers"] == []
    assert report["checks"]["diarization"] is True


def test_modelrig_probe_reports_tts(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"tts": True, "cuda": True}

    monkeypatch.setattr(rv.httpx, "get", lambda _url, timeout: Response())

    report = rv._probe_modelrig("http://127.0.0.1:8099")

    assert report["reachable"] is True
    assert report["tts"] is True
    assert report["capabilities"]["cuda"] is True


def test_modelrig_probe_fails_closed(monkeypatch):
    def fail(_url, timeout):
        raise rv.httpx.ConnectError("offline")

    monkeypatch.setattr(rv.httpx, "get", fail)

    report = rv._probe_modelrig("http://127.0.0.1:8099")

    assert report["reachable"] is False
    assert report["tts"] is False
