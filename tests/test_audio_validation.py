import math
import struct
import wave
from pathlib import Path

import pytest

from voicerig.media.audio import AudioValidationError, validate_wav


def _write_tone(path: Path, seconds: float = 1.0, rate: int = 24000, amplitude: int = 5000):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        data = bytearray()
        for i in range(frames):
            sample = int(amplitude * math.sin(2 * math.pi * 220 * i / rate))
            data.extend(struct.pack("<h", sample))
        wav.writeframes(bytes(data))


def test_validate_wav_accepts_audible_audio(tmp_path: Path):
    path = tmp_path / "tone.wav"
    _write_tone(path)

    info = validate_wav(path, min_duration_s=0.5, max_duration_s=2.0)

    assert 0.99 < info["duration"] < 1.01
    assert info["sample_rate"] == 24000
    assert info["rms"] > 0.0


def test_validate_wav_rejects_silence(tmp_path: Path):
    path = tmp_path / "silent.wav"
    _write_tone(path, amplitude=0)

    with pytest.raises(AudioValidationError, match="ingen målbar lyd"):
        validate_wav(path)


def test_validate_wav_rejects_implausibly_short_audio(tmp_path: Path):
    path = tmp_path / "short.wav"
    _write_tone(path, seconds=0.1)

    with pytest.raises(AudioValidationError, match="for kort"):
        validate_wav(path, min_duration_s=0.5)
