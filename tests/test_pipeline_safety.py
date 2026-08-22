from pathlib import Path

import pytest

import voicerig.app.pipeline as pipeline
from voicerig.analysis.diarization import DiarizationUnavailable
from voicerig.analysis.reference import ReferenceCandidate


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


def test_cross_file_reference_uses_multi_source_stitcher(tmp_path: Path, monkeypatch):
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    target = tmp_path / "reference.wav"
    candidate = ReferenceCandidate(
        source=first,
        start=0.0,
        duration=6.0,
        score=0.9,
        speaker="pooled",
        source_parts=((first, 0.0, 3.0), (second, 1.0, 3.0)),
    )
    captured = {}

    def fake_multi(parts, output):
        captured["parts"] = list(parts)
        output.write_bytes(b"RIFF" + b"\0" * 256)
        return output

    monkeypatch.setattr(pipeline, "stitch_wav_sources", fake_multi)
    monkeypatch.setattr(
        pipeline,
        "stitch_wav_segments",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("single-source stitcher used")),
    )
    monkeypatch.setattr(
        pipeline,
        "cut_wav",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("single-source cutter used")),
    )
    monkeypatch.setattr(pipeline, "validate_wav", lambda *_args, **_kwargs: {"duration": 6.08})

    result = pipeline._materialize_reference(candidate, target)

    assert result == target
    assert captured["parts"] == list(candidate.source_parts)
    assert pipeline._reference_source_count(candidate) == 2


def test_unsafe_undiarized_fallback_is_explicit(monkeypatch):
    import voicerig.config as config

    monkeypatch.delenv("VOICERIG_ALLOW_UNDIARIZED", raising=False)
    assert config.allow_undiarized_fallback() is False

    monkeypatch.setenv("VOICERIG_ALLOW_UNDIARIZED", "1")
    assert config.allow_undiarized_fallback() is True
