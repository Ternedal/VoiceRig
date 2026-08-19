from pathlib import Path

import pytest

import voicerig.app.pipeline as pipeline
from voicerig.analysis.diarization import DiarizationUnavailable


def test_voice_build_fails_closed_when_diarization_is_unavailable(tmp_path: Path, monkeypatch):
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"fake-media")

    def fake_extract(_source: Path, target: Path):
        target.write_bytes(b"RIFF" + b"\0" * 256)
        return target

    monkeypatch.setattr(pipeline, "extract_mono_wav", fake_extract)
    monkeypatch.setattr(
        pipeline,
        "diarize_many",
        lambda _wavs: (_ for _ in ()).throw(DiarizationUnavailable("model unavailable")),
    )
    monkeypatch.setattr(pipeline, "allow_undiarized_fallback", lambda: False)

    with pytest.raises(RuntimeError, match="sikker speaker-analyse"):
        pipeline.create_voice("Test", [source], tmp_path / "out")


def test_unsafe_undiarized_fallback_is_explicit(monkeypatch):
    import voicerig.config as config

    monkeypatch.delenv("VOICERIG_ALLOW_UNDIARIZED", raising=False)
    assert config.allow_undiarized_fallback() is False

    monkeypatch.setenv("VOICERIG_ALLOW_UNDIARIZED", "1")
    assert config.allow_undiarized_fallback() is True
