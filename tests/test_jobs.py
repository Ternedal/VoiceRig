from __future__ import annotations

import time
from pathlib import Path

import voicerig.app.jobs as jobs
from voicerig.app.jobs import VoiceJobManager
from voicerig.app.pipeline import BuildResult, ReferenceSelectionRequired, SpeakerSelectionRequired


def _configure(monkeypatch, tmp_path: Path):
    root = tmp_path / "data"
    monkeypatch.setattr(jobs, "data_dir", lambda: root)
    monkeypatch.setattr(jobs, "reset_cuda_peaks", lambda: True)
    monkeypatch.setattr(jobs, "cuda_memory_stats", lambda: {"available": False})
    monkeypatch.setattr(jobs, "source_status", lambda: {"revision": "test"})
    monkeypatch.setattr(
        jobs,
        "validate_package",
        lambda package: {"id": "voice-12345678", "name": "Test Voice", "language": "da"},
    )
    return root


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "input.wav"
    source.write_bytes(b"RIFF-test")
    return source


def _wait(manager: VoiceJobManager, job_id: str, wanted: set[str], timeout: float = 3.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        current = manager.get(job_id)
        if current["state"] in wanted:
            return current
        time.sleep(0.02)
    raise AssertionError(f"job did not reach {wanted}: {manager.get(job_id)}")


def _successful_build(name, sources, output_dir, language="da", speaker_anchor=None, progress=None, **kwargs):
    if progress:
        progress("decoding", 20, "decode")
        progress("conditioning", 70, "conditioning")
    output_dir.mkdir(parents=True, exist_ok=True)
    package = output_dir / "test-voice.mrvoice"
    package.write_bytes(b"package")
    reference = output_dir / "test-voice-reference.wav"
    reference.write_bytes(b"RIFF-reference")
    if progress:
        progress("complete", 100, "complete")
    return BuildResult(package=package, reference=reference, diarization_used=True)


def _reference_choices():
    return [
        {
            "choice": 1,
            "label": "Reference 1",
            "quality_score": 0.91,
            "reference_seconds": 9.8,
            "preview_duration": 4.0,
            "preview_wav_base64": "UklGRg==",
        },
        {
            "choice": 2,
            "label": "Reference 2",
            "quality_score": 0.86,
            "reference_seconds": 10.0,
            "preview_duration": 4.0,
            "preview_wav_base64": "UklGRg==",
        },
    ]


def test_job_runs_to_success_and_removes_source_copies(monkeypatch, tmp_path: Path):
    root = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(jobs, "create_voice", _successful_build)
    manager = VoiceJobManager()
    try:
        created = manager.create("Test Voice", "da", False, [("input.wav", _source(tmp_path))])
        finished = _wait(manager, created["id"], {"succeeded"})

        assert finished["progress"] == 100
        assert finished["result"]["voice"]["name"] == "Test Voice"
        assert finished["result"]["package"] == "test-voice.mrvoice"
        assert not (root / "jobs" / created["id"]).exists()
        assert (root / "jobs" / f"{created['id']}.json").is_file()
    finally:
        manager._executor.shutdown(wait=True)


def test_job_pauses_for_speaker_and_resumes_from_stable_anchor(monkeypatch, tmp_path: Path):
    root = _configure(monkeypatch, tmp_path)

    def build(name, sources, output_dir, language="da", speaker_anchor=None, progress=None, **kwargs):
        if speaker_anchor is None:
            raise SpeakerSelectionRequired(
                [
                    {"choice": 1, "anchor": "0:1.000", "label": "Stemme 1", "speech_seconds": 4.0, "preview_duration": 2.0, "preview_wav_base64": "UklGRg=="},
                    {"choice": 2, "anchor": "0:5.000", "label": "Stemme 2", "speech_seconds": 3.0, "preview_duration": 2.0, "preview_wav_base64": "UklGRg=="},
                ]
            )
        assert speaker_anchor == "0:5.000"
        return _successful_build(name, sources, output_dir, language, speaker_anchor, progress)

    monkeypatch.setattr(jobs, "create_voice", build)
    manager = VoiceJobManager()
    try:
        created = manager.create("Test Voice", "da", False, [("input.wav", _source(tmp_path))])
        waiting = _wait(manager, created["id"], {"needs_speaker"})
        assert len(waiting["speaker_choices"]) == 2
        assert (root / "jobs" / created["id"]).is_dir()
        with manager._lock:
            assert created["id"] not in manager._active

        manager.choose_speaker(created["id"], "0:5.000")
        finished = _wait(manager, created["id"], {"succeeded"})
        assert finished["result"]["voice"]["name"] == "Test Voice"
        assert not (root / "jobs" / created["id"]).exists()
    finally:
        manager._executor.shutdown(wait=True)


def test_job_pauses_for_reference_auditions_and_resumes_selected_candidate(monkeypatch, tmp_path: Path):
    root = _configure(monkeypatch, tmp_path)

    def build(name, sources, output_dir, language="da", reference_choice=None, progress=None, **kwargs):
        if reference_choice is None:
            raise ReferenceSelectionRequired(_reference_choices())
        assert reference_choice == 2
        return _successful_build(name, sources, output_dir, language, progress=progress)

    monkeypatch.setattr(jobs, "create_voice", build)
    manager = VoiceJobManager()
    try:
        created = manager.create("Test Voice", "da", False, [("input.wav", _source(tmp_path))])
        waiting = _wait(manager, created["id"], {"needs_reference"})
        assert waiting["progress"] == 65
        assert len(waiting["reference_choices"]) == 2
        assert waiting["reference_choices"][1]["quality_score"] == 0.86
        assert (root / "jobs" / created["id"]).is_dir()
        with manager._lock:
            assert created["id"] not in manager._active

        resumed = manager.choose_reference(created["id"], 2)
        assert resumed["state"] in {"queued", "running"}
        assert resumed["reference_choices"] is None

        finished = _wait(manager, created["id"], {"succeeded"})
        assert finished["result"]["voice"]["name"] == "Test Voice"
        assert not (root / "jobs" / created["id"]).exists()
    finally:
        manager._executor.shutdown(wait=True)


def test_cancel_while_waiting_for_speaker_is_immediate(monkeypatch, tmp_path: Path):
    root = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(
        jobs,
        "create_voice",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            SpeakerSelectionRequired(
                [
                    {"choice": 1, "anchor": "0:1.000"},
                    {"choice": 2, "anchor": "0:2.000"},
                ]
            )
        ),
    )
    manager = VoiceJobManager()
    try:
        created = manager.create("Test Voice", "da", False, [("input.wav", _source(tmp_path))])
        _wait(manager, created["id"], {"needs_speaker"})
        cancelled = manager.cancel(created["id"])
        assert cancelled["state"] == "cancelled"
        assert cancelled["speaker_choices"] is None
        assert not (root / "jobs" / created["id"]).exists()
    finally:
        manager._executor.shutdown(wait=True)


def test_cancel_while_waiting_for_reference_is_immediate(monkeypatch, tmp_path: Path):
    root = _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(
        jobs,
        "create_voice",
        lambda *args, **kwargs: (_ for _ in ()).throw(ReferenceSelectionRequired(_reference_choices())),
    )
    manager = VoiceJobManager()
    try:
        created = manager.create("Test Voice", "da", False, [("input.wav", _source(tmp_path))])
        _wait(manager, created["id"], {"needs_reference"})
        cancelled = manager.cancel(created["id"])
        assert cancelled["state"] == "cancelled"
        assert cancelled["reference_choices"] is None
        assert not (root / "jobs" / created["id"]).exists()
    finally:
        manager._executor.shutdown(wait=True)


def test_speaker_selection_rejects_anchor_not_from_job(monkeypatch, tmp_path: Path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(
        jobs,
        "create_voice",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            SpeakerSelectionRequired(
                [
                    {"choice": 1, "anchor": "0:1.000"},
                    {"choice": 2, "anchor": "0:2.000"},
                ]
            )
        ),
    )
    manager = VoiceJobManager()
    try:
        created = manager.create("Test Voice", "da", False, [("input.wav", _source(tmp_path))])
        _wait(manager, created["id"], {"needs_speaker"})
        try:
            manager.choose_speaker(created["id"], "9:999.000")
        except ValueError as exc:
            assert "hører ikke til" in str(exc)
        else:
            raise AssertionError("invalid speaker anchor was accepted")
    finally:
        manager._executor.shutdown(wait=True)


def test_reference_selection_rejects_choice_not_from_job(monkeypatch, tmp_path: Path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(
        jobs,
        "create_voice",
        lambda *args, **kwargs: (_ for _ in ()).throw(ReferenceSelectionRequired(_reference_choices())),
    )
    manager = VoiceJobManager()
    try:
        created = manager.create("Test Voice", "da", False, [("input.wav", _source(tmp_path))])
        _wait(manager, created["id"], {"needs_reference"})
        try:
            manager.choose_reference(created["id"], 4)
        except ValueError as exc:
            assert "hører ikke til" in str(exc)
        else:
            raise AssertionError("invalid reference choice was accepted")
    finally:
        manager._executor.shutdown(wait=True)
