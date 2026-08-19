from __future__ import annotations

from pathlib import Path

import voicerig.release_gate as release_gate


def _write(path: Path, payload: bytes = b"RIFF" + b"x" * 128) -> str:
    path.write_bytes(payload)
    return str(path)


def _evidence(tmp_path: Path) -> tuple[dict, dict]:
    package = _write(tmp_path / "voice.mrvoice", b"package")
    reference = _write(tmp_path / "voice-reference.wav")
    validation_wav = _write(tmp_path / "voice-validation.wav")
    piper_wav = _write(tmp_path / "piper-fallback.wav")

    validation = {
        "ok": True,
        "stage": "complete",
        "blockers": [],
        "source_evidence": {
            "same_revision": True,
            "checkout": {"revision": "abc123", "dirty": False},
            "service": {"source": {"revision": "abc123", "dirty": False}},
        },
        "preflight": {"readiness": {"hardware": {"vram_total_gb": 12.0}}},
        "voice": {
            "package": package,
            "reference": reference,
            "validation_wav": validation_wav,
            "diarization_used": True,
        },
        "synthesis": {"headers": {"device": "cuda", "package": "voice.mrvoice"}},
        "gpu": {
            "after_build": {"peak_reserved_gb": 8.5},
            "after_synthesis": {"peak_reserved_gb": 9.0},
        },
        "speaker_similarity": {"available": True, "cosine": 0.81},
        "modelrig": {
            "reachable": True,
            "authenticated": True,
            "tts": True,
            "provider": "voicerig",
            "package_matches": True,
        },
    }
    fallback = {
        "ok": True,
        "checkout_revision": "abc123",
        "fallback": {"ok": True, "provider": "piper"},
        "piper_synthesis": {"provider": "piper", "riff": True, "output": piper_wav},
        "restarted": True,
        "restarted_service_revision": "abc123",
        "restored": {"ok": True, "provider": "voicerig"},
    }
    return validation, fallback


def test_release_gate_passes_only_with_complete_machine_and_human_evidence(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        release_gate,
        "source_status",
        lambda: {"available": True, "revision": "abc123", "dirty": False, "branch": "agent/voicerig-mvp"},
    )
    validation, fallback = _evidence(tmp_path)

    report = release_gate.evaluate_release(
        validation,
        fallback,
        quality_pass=True,
        quality_note="Tydelig dansk, genkendelig stemme og ingen alvorlige artefakter.",
    )

    assert report["ok"] is True
    assert report["stage"] == "release-ready"
    assert report["artifacts"]["package"]["sha256"]
    assert report["artifacts"]["validation_wav"]["sha256"]
    assert report["artifacts"]["piper_fallback_wav"]["sha256"]


def test_release_gate_rejects_missing_manual_quality_pass(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        release_gate,
        "source_status",
        lambda: {"available": True, "revision": "abc123", "dirty": False},
    )
    validation, fallback = _evidence(tmp_path)

    report = release_gate.evaluate_release(validation, fallback, quality_pass=False, quality_note="")

    assert report["ok"] is False
    assert any("lyttekontrol" in blocker for blocker in report["blockers"])


def test_release_gate_rejects_stale_revision_and_missing_artifact(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        release_gate,
        "source_status",
        lambda: {"available": True, "revision": "new-head", "dirty": False},
    )
    validation, fallback = _evidence(tmp_path)
    Path(validation["voice"]["validation_wav"]).unlink()

    report = release_gate.evaluate_release(
        validation,
        fallback,
        quality_pass=True,
        quality_note="Lyden er manuelt vurderet.",
    )

    assert report["ok"] is False
    assert any("revision" in blocker.lower() for blocker in report["blockers"])
    assert any("validation WAV" in blocker for blocker in report["blockers"])


def test_complete_acceptance_wrapper_requires_explicit_quality_acknowledgement():
    root = Path(__file__).resolve().parents[1]
    text = (root / "complete-acceptance.ps1").read_text(encoding="utf-8")

    assert "[switch]$QualityPass" in text
    assert "-QualityPass kræver også -QualityNote" in text
    assert "-m voicerig.release_gate" in text
    assert "release-acceptance.json" in text
