import base64
import math
import struct
import wave
from pathlib import Path

import pytest

import voicerig.app.pipeline as pipeline
from voicerig.analysis.diarization import DiarizationResult, Segment, Speaker


def _write_tone(path: Path, seconds: float = 12.0, rate: int = 24000):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        data = bytearray()
        for i in range(frames):
            sample = int(5000 * math.sin(2 * math.pi * 220 * i / rate))
            data.extend(struct.pack("<h", sample))
        wav.writeframes(bytes(data))


def _fake_extract(_source: Path, target: Path):
    _write_tone(target)
    return target


def _ambiguous_results(wavs: list[Path]):
    wav = wavs[0]
    return [
        DiarizationResult(
            wav,
            (Segment(0.0, 6.0, "A"), Segment(6.0, 12.0, "B")),
            (
                Speaker(wav, "A", 6.0, (1.0, 0.0)),
                Speaker(wav, "B", 6.0, (0.0, 1.0)),
            ),
        )
    ]


def test_ambiguous_build_returns_two_playable_choices_before_loading_chatterbox(tmp_path: Path, monkeypatch):
    source = tmp_path / "interview.mp4"
    source.write_bytes(b"media")
    monkeypatch.setattr(pipeline, "extract_mono_wav", _fake_extract)
    monkeypatch.setattr(pipeline, "diarize_many", _ambiguous_results)

    class MustNotLoad:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Chatterbox must not load before speaker selection")

    monkeypatch.setattr(pipeline, "ChatterboxEngine", MustNotLoad)

    with pytest.raises(pipeline.SpeakerSelectionRequired) as caught:
        pipeline.create_voice("Interview", [source], tmp_path / "out")

    choices = caught.value.choices
    assert [item["choice"] for item in choices] == [1, 2]
    assert all(item["speech_seconds"] == 6.0 for item in choices)
    for item in choices:
        raw = base64.b64decode(item["preview_wav_base64"], validate=True)
        assert raw[:4] == b"RIFF"
        assert len(raw) > 1000


def test_explicit_choice_builds_selected_voice_without_ambiguity_loop(tmp_path: Path, monkeypatch):
    source = tmp_path / "interview.mp4"
    source.write_bytes(b"media")
    monkeypatch.setattr(pipeline, "extract_mono_wav", _fake_extract)
    monkeypatch.setattr(pipeline, "diarize_many", _ambiguous_results)

    class FakeEngine:
        def __init__(self, language="da"):
            self.language = language

        def build_artifacts(self, reference: Path, conditioning: Path, preview: Path):
            conditioning.write_bytes(b"conditioning")
            _write_tone(preview, seconds=1.0)
            return conditioning, preview

    monkeypatch.setattr(pipeline, "ChatterboxEngine", FakeEngine)

    result = pipeline.create_voice(
        "Valgt stemme",
        [source],
        tmp_path / "out",
        speaker_choice=2,
    )

    assert result.diarization_used is True
    assert result.package.is_file()
    assert result.reference.is_file()
    assert 5.9 < pipeline.validate_wav(result.reference)["duration"] < 6.1
