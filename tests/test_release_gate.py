from __future__ import annotations

from pathlib import Path

import voicerig.release_gate as release_gate


def _write(path: Path, payload: bytes = b"RIFF" + b"x" * 128) -> str:
    path.write_bytes(payload)
    return str(path)


def _root(tmp_path: Path) -> str:
    return str((tmp_path / "checkout").resolve())


def _source(tmp_path: Path, revision: str = "abc123") -> dict:
    return {
        "available": True,
        "revision": revision,
        "dirty": False,
        "branch": "agent/voicerig-mvp",
        "root": _root(tmp_path),
    }


def _evidence(tmp_path: Path) -> tuple[dict, dict]:
    package = _write(tmp_path / "voice.mrvoice", b"package")
    reference = _write(tmp_path / "voice-reference.wav")
    validation_wav = _write(tmp_path / "voice-validation.wav")
    piper_wav = _write(tmp_path / "piper-fallback.wav")
    root = _root(tmp_path)

    validation = {
        "ok": True,
        "stage": "complete",
        "blockers": [],
        "source_evidence": {
            "same_revision": True,
            "same_root": True,
            "checkout": {"revision": "abc123", "dirty": False, "root": root},
            "service": {"source": {"revision": "abc123", "dirty": False, "root": root}},
        },
        "preflight": {"readiness": {"hardware": {"vram_total_gb": 12.0}}},
        "voice": {
            "id": "voice",
            "name": "Voice",
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
        "checkout_root": root,
        "before": {"ok": True, "provider": "voicerig", "package": "voice.mrvoice"},
        "fallback": {"ok": True, "provider": "piper"},
        "piper_synthesis": {"provider": "piper", "riff": True, "output": piper_wav},
        "restarted": True,
        "restarted_service_revision": "abc123",
        "restarted_service_root": root,
        "restored": {"ok": True, "provider": "voicerig", "package": "voice.mrvoice"},
    }
    return validation, fallback


def _stub_validators(monkeypatch):
    monkeypatch.setattr(
        release_gate,
        "validate_package",
        lambda path: {"id": "voice", "name": "Voice"},
    )
    monkeypatch.setattr(
        release_gate,
        "validate_wav",
        lambda path, **kwargs: {"sample_rate": 24000, "duration": 2.0, "rms": 0.1},
    )


def test_release_gate_passes_only_with_complete_machine_and_human_evidence(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(release_gate, "source_status", lambda: _source(tmp_path))
    _stub_validators(monkeypatch)
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
    assert report["artifacts"]["package"]["validated"] is True
    assert report["artifacts"]["validation_wav"]["sha256"]
    assert report["artifacts"]["validation_wav"]["validated"] is True
    assert report["artifacts"]["piper_fallback_wav"]["sha256"]
    assert report["artifacts"]["piper_fallback_wav"]["validated"] is True
    assert report["fallback"]["before_package"] == "voice.mrvoice"
    assert report["fallback"]["restored_package"] == "voice.mrvoice"


def test_release_gate_rejects_missing_manual_quality_pass(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(release_gate, "source_status", lambda: _source(tmp_path))
    _stub_validators(monkeypatch)
    validation, fallback = _evidence(tmp_path)

    report = release_gate.evaluate_release(validation, fallback, quality_pass=False, quality_note="")

    assert report["ok"] is False
    assert any("lyttekontrol" in blocker for blocker in report["blockers"])


def test_release_gate_rejects_stale_revision_and_missing_artifact(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(release_gate, "source_status", lambda: _source(tmp_path, "new-head"))
    _stub_validators(monkeypatch)
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


def test_release_gate_rejects_same_revision_from_different_checkout(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(release_gate, "source_status", lambda: _source(tmp_path))
    _stub_validators(monkeypatch)
    validation, fallback = _evidence(tmp_path)
    foreign = str((tmp_path / "foreign-checkout").resolve())
    validation["source_evidence"]["same_root"] = False
    validation["source_evidence"]["service"]["source"]["root"] = foreign
    fallback["checkout_root"] = foreign
    fallback["restarted_service_root"] = foreign

    report = release_gate.evaluate_release(
        validation,
        fallback,
        quality_pass=True,
        quality_note="Lyden er manuelt vurderet.",
    )

    assert report["ok"] is False
    assert any("checkout-root" in blocker or "release-checkout" in blocker for blocker in report["blockers"])


def test_release_gate_rejects_artifact_that_changed_after_machine_pass(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(release_gate, "source_status", lambda: _source(tmp_path))
    validation, fallback = _evidence(tmp_path)

    def broken_package(path):
        raise ValueError("checksum mismatch")

    monkeypatch.setattr(release_gate, "validate_package", broken_package)
    monkeypatch.setattr(
        release_gate,
        "validate_wav",
        lambda path, **kwargs: {"sample_rate": 24000, "duration": 2.0, "rms": 0.1},
    )

    report = release_gate.evaluate_release(
        validation,
        fallback,
        quality_pass=True,
        quality_note="Lyden blev vurderet før package-integriteten ændrede sig.",
    )

    assert report["ok"] is False
    assert any("kan ikke længere valideres" in blocker for blocker in report["blockers"])


def test_release_gate_rejects_fallback_for_different_voice_package(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(release_gate, "source_status", lambda: _source(tmp_path))
    _stub_validators(monkeypatch)
    validation, fallback = _evidence(tmp_path)
    fallback["before"]["package"] = "other.mrvoice"
    fallback["restored"]["package"] = "other.mrvoice"

    report = release_gate.evaluate_release(
        validation,
        fallback,
        quality_pass=True,
        quality_note="Lyden er vurderet.",
    )

    assert report["ok"] is False
    assert any("starttilstand" in blocker for blocker in report["blockers"])
    assert any("vendte ModelRig ikke tilbage" in blocker for blocker in report["blockers"])


def test_complete_acceptance_wrapper_requires_explicit_quality_acknowledgement():
    root = Path(__file__).resolve().parents[1]
    text = (root / "complete-acceptance.ps1").read_text(encoding="utf-8")

    assert "[switch]$QualityPass" in text
    assert "-QualityPass kræver også -QualityNote" in text
    assert "-m voicerig.release_gate" in text
    assert "release-acceptance.json" in text
