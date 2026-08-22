from __future__ import annotations

import threading
from pathlib import Path

import pytest

from voicerig.app import pipeline


def test_nonblocking_build_is_rejected_while_shared_gate_is_busy(tmp_path: Path, monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def fake_impl(
        name,
        sources,
        output_dir,
        language,
        speaker_choice,
        speaker_anchor,
        reference_choice,
        progress,
    ):
        entered.set()
        assert release.wait(timeout=3)
        return pipeline.BuildResult(
            package=tmp_path / "voice.mrvoice",
            reference=tmp_path / "voice-reference.wav",
            diarization_used=True,
        )

    monkeypatch.setattr(pipeline, "_create_voice_impl", fake_impl)
    source = tmp_path / "input.wav"
    source.write_bytes(b"x")

    errors: list[Exception] = []

    def run_first():
        try:
            pipeline.create_voice("First", [source], tmp_path)
        except Exception as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    thread = threading.Thread(target=run_first)
    thread.start()
    assert entered.wait(timeout=2)
    assert pipeline.build_gate_status()["busy"] is True

    with pytest.raises(pipeline.VoiceBuildBusy, match="allerede"):
        pipeline.create_voice(
            "Second",
            [source],
            tmp_path,
            wait_for_build_slot=False,
        )

    release.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert errors == []
    assert pipeline.build_gate_status()["busy"] is False
