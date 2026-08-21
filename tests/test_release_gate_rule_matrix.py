from __future__ import annotations

from pathlib import Path

import pytest

import voicerig.release_gate as release_gate


QUALITY_NOTE = "Tydelig dansk, genkendelig stemme og ingen alvorlige artefakter."
FOREIGN_ROOT = "<foreign-root>"
SHORT_PIPER_WAV = "<short-piper-wav>"


def _write(path: Path, payload: bytes = b"RIFF" + b"x" * 128) -> str:
    path.write_bytes(payload)
    return str(path)


def _root(tmp_path: Path) -> str:
    return str((tmp_path / "checkout").resolve())


def _source(tmp_path: Path) -> dict:
    return {
        "available": True,
        "revision": "abc123",
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


def _stub_validators(monkeypatch) -> None:
    monkeypatch.setattr(release_gate, "validate_package", lambda path: {"id": "voice", "name": "Voice"})
    monkeypatch.setattr(
        release_gate,
        "validate_wav",
        lambda path, **kwargs: {"sample_rate": 24000, "duration": 2.0, "rms": 0.1},
    )


def _set_path(target: dict, path: str, value: object) -> None:
    parts = path.split(".")
    current = target
    for part in parts[:-1]:
        current = current[part]
    current[parts[-1]] = value


CASES = [
    ("source.available", False, "Git HEAD kunne ikke aflæses"),
    ("source.revision", "", "Git HEAD kunne ikke aflæses"),
    ("source.dirty", True, "Checkoutet er dirty"),
    ("source.root", "", "Checkout-root kunne ikke aflæses"),
    ("validation.ok", False, "validation-report.json er ikke et komplet PASS"),
    ("validation.stage", "running", "validation-report.json er ikke et komplet PASS"),
    ("validation.blockers", ["machine blocker"], "validation-report.json indeholder blockers"),
    ("validation.source_evidence.same_revision", False, "ikke på samme revision"),
    ("validation.source_evidence.same_root", False, "ikke fra samme checkout-root"),
    ("validation.source_evidence.checkout.revision", "old", "checkout revision matcher ikke"),
    ("validation.source_evidence.checkout.dirty", True, "checkout var dirty"),
    ("validation.source_evidence.checkout.root", FOREIGN_ROOT, "checkout-root matcher ikke"),
    ("validation.source_evidence.service.source.revision", "old", "aktive VoiceRig-service matcher ikke"),
    ("validation.source_evidence.service.source.dirty", True, "VoiceRig-service kørte fra et dirty checkout"),
    ("validation.source_evidence.service.source.root", FOREIGN_ROOT, "aktive VoiceRig-service kom ikke fra"),
    ("validation.voice.diarization_used", False, "brugte ikke speaker-diarization"),
    ("validation.voice.id", "other-id", "manifest-id matcher ikke"),
    ("validation.voice.name", "Other Voice", "manifest-navn matcher ikke"),
    ("validation.synthesis.headers.device", "cpu", "rapporterede ikke CUDA"),
    ("validation.synthesis.headers.package", "other.mrvoice", "brugte ikke den .mrvoice-pakke"),
    ("validation.gpu.after_build.peak_reserved_gb", None, "Peak VRAM mangler for build"),
    ("validation.gpu.after_build.peak_reserved_gb", 13.0, "peak VRAM for build overstiger"),
    ("validation.gpu.after_synthesis.peak_reserved_gb", None, "Peak VRAM mangler for syntese"),
    ("validation.gpu.after_synthesis.peak_reserved_gb", 13.0, "peak VRAM for syntese overstiger"),
    ("validation.modelrig.reachable", False, "ModelRig-backenden var ikke reachable"),
    ("validation.modelrig.authenticated", False, "ModelRig-backenden var ikke autentificeret"),
    ("validation.modelrig.tts", False, "ikke VoiceRig som fungerende TTS-provider"),
    ("validation.modelrig.provider", "piper", "ikke VoiceRig som fungerende TTS-provider"),
    ("validation.modelrig.package_matches", False, "brugte ikke den netop byggede .mrvoice-pakke"),
    ("fallback.ok", False, "piper-fallback-report.json er ikke PASS"),
    ("fallback.checkout_revision", "old", "Piper fallback blev ikke testet på nuværende Git HEAD"),
    ("fallback.checkout_root", FOREIGN_ROOT, "Piper fallback blev ikke kørt fra den nuværende release-checkout"),
    ("fallback.before.ok", False, "startede ikke dokumenteret fra VoiceRig-provider"),
    ("fallback.before.provider", "piper", "startede ikke dokumenteret fra VoiceRig-provider"),
    ("fallback.before.package", "other.mrvoice", "starttilstand brugte ikke acceptance-buildets"),
    ("fallback.fallback.ok", False, "skiftede ikke dokumenteret til Piper"),
    ("fallback.fallback.provider", "voicerig", "skiftede ikke dokumenteret til Piper"),
    ("fallback.piper_synthesis.provider", "voicerig", "Piper fallback producerede ikke en dokumenteret RIFF/WAV"),
    ("fallback.piper_synthesis.riff", False, "Piper fallback producerede ikke en dokumenteret RIFF/WAV"),
    ("fallback.piper_synthesis.output", SHORT_PIPER_WAV, "Piper fallback WAV er tom eller ugyldigt kort"),
    ("fallback.restarted", False, "VoiceRig blev ikke dokumenteret genstartet"),
    ("fallback.restarted_service_revision", "old", "genstartede VoiceRig-service matcher ikke"),
    ("fallback.restarted_service_root", FOREIGN_ROOT, "genstartede VoiceRig-service kom ikke fra"),
    ("fallback.restored.ok", False, "vendte ikke dokumenteret tilbage til VoiceRig"),
    ("fallback.restored.provider", "piper", "vendte ikke dokumenteret tilbage til VoiceRig"),
    ("fallback.restored.package", "other.mrvoice", "Efter fallback vendte ModelRig ikke tilbage"),
    ("quality.pass", False, "Manuel lyttekontrol er ikke eksplicit godkendt"),
    ("quality.note", "", "Manuel lyttekontrol kræver en kort kvalitetsnote"),
]


@pytest.mark.parametrize("field_path,failing_value,expected_blocker", CASES, ids=[case[0] for case in CASES])
def test_release_gate_rule_matrix(
    monkeypatch,
    tmp_path: Path,
    field_path: str,
    failing_value: object,
    expected_blocker: str,
) -> None:
    source = _source(tmp_path)
    validation, fallback = _evidence(tmp_path)
    quality = {"pass": True, "note": QUALITY_NOTE}
    _stub_validators(monkeypatch)
    monkeypatch.setattr(release_gate, "source_status", lambda: source)

    if failing_value == FOREIGN_ROOT:
        failing_value = str((tmp_path / "foreign-checkout").resolve())
    elif failing_value == SHORT_PIPER_WAV:
        failing_value = _write(tmp_path / "short-piper.wav", b"RIFF" + b"x" * 16)

    namespace, path = field_path.split(".", 1)
    target = {"source": source, "validation": validation, "fallback": fallback, "quality": quality}[namespace]
    _set_path(target, path, failing_value)

    report = release_gate.evaluate_release(
        validation,
        fallback,
        quality_pass=quality["pass"],
        quality_note=quality["note"],
    )

    assert report["ok"] is False
    assert any(expected_blocker in blocker for blocker in report["blockers"]), report["blockers"]


def test_release_gate_rule_matrix_baseline_is_actually_green(monkeypatch, tmp_path: Path) -> None:
    source = _source(tmp_path)
    validation, fallback = _evidence(tmp_path)
    _stub_validators(monkeypatch)
    monkeypatch.setattr(release_gate, "source_status", lambda: source)

    report = release_gate.evaluate_release(
        validation,
        fallback,
        quality_pass=True,
        quality_note=QUALITY_NOTE,
    )

    assert report["ok"] is True
    assert report["blockers"] == []
