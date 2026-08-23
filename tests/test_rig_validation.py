from __future__ import annotations

from types import SimpleNamespace

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
    assert "Chatterbox V3 er ikke installeret i hovedmiljøet." in report["blockers"]
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


def test_modelrig_probe_uses_authenticated_backend_and_verifies_voicerig_package(monkeypatch):
    captured = {}

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "checks": {
                    "tts": {
                        "ok": True,
                        "provider": "voicerig",
                        "package": "anders.mrvoice",
                        "device": "cuda",
                    }
                }
            }

    def fake_get(url, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr(rv.httpx, "get", fake_get)
    report = rv._probe_modelrig(
        "http://127.0.0.1:8080",
        "secret-token",
        expected_package="anders.mrvoice",
    )

    assert captured["url"] == "http://127.0.0.1:8080/api/v1/health/full"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert report["reachable"] is True
    assert report["authenticated"] is True
    assert report["tts"] is True
    assert report["provider"] == "voicerig"
    assert report["package_matches"] is True


def test_modelrig_probe_reports_missing_token_as_auth_failure(monkeypatch):
    class Response:
        status_code = 401

    monkeypatch.setattr(rv.httpx, "get", lambda url, headers, timeout: Response())

    report = rv._probe_modelrig("http://127.0.0.1:8080", None)

    assert report["reachable"] is True
    assert report["authenticated"] is False
    assert report["tts"] is False
    assert "MODELRIG_TOKEN" in report["detail"]


def test_modelrig_probe_fails_closed_when_backend_is_offline(monkeypatch):
    def fail(url, headers, timeout):
        raise rv.httpx.ConnectError("offline")

    monkeypatch.setattr(rv.httpx, "get", fail)

    report = rv._probe_modelrig("http://127.0.0.1:8080", "token")

    assert report["reachable"] is False
    assert report["tts"] is False


def test_voice_service_status_requires_ready_body(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ready": True, "hardware": {"gpu": "RTX 3060"}}

    monkeypatch.setattr(rv.httpx, "get", lambda url, timeout: Response())
    report = rv._voice_service_status("http://127.0.0.1:8765")

    assert report["reachable"] is True
    assert report["ready"] is True
    assert report["url"].endswith("/api/readiness")


def test_header_float_rejects_nonfinite_values():
    assert rv._header_float({"x": "12.5"}, "x") == 12.5
    assert rv._header_float({"x": "nan"}, "x") is None
    assert rv._header_float({}, "x") is None


def test_speaker_similarity_reports_cosine_without_inventing_threshold(monkeypatch, tmp_path):
    ref = SimpleNamespace(
        speakers=(SimpleNamespace(duration=8.0, embedding=(1.0, 0.0)),)
    )
    synth = SimpleNamespace(
        speakers=(SimpleNamespace(duration=7.0, embedding=(0.8, 0.6)),)
    )
    monkeypatch.setattr(rv, "diarize_many", lambda _paths: [ref, synth])

    report = rv._measure_speaker_similarity(tmp_path / "ref.wav", tmp_path / "synth.wav")

    assert report["available"] is True
    assert report["cosine"] == 0.8
    assert report["calibrated_threshold"] is None


def test_speaker_similarity_is_nonfatal_when_embedding_is_missing(monkeypatch, tmp_path):
    no_embedding = SimpleNamespace(
        speakers=(SimpleNamespace(duration=8.0, embedding=None),)
    )
    monkeypatch.setattr(rv, "diarize_many", lambda _paths: [no_embedding, no_embedding])

    report = rv._measure_speaker_similarity(tmp_path / "ref.wav", tmp_path / "synth.wav")

    assert report["available"] is False
    assert report["cosine"] is None
