import math
import struct
import wave
from pathlib import Path

from voicerig.analysis.reference import select_reference, wav_duration


def make_tone(path: Path, seconds: float = 7.0, rate: int = 24000):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(rate)
        data = bytearray()
        for i in range(frames):
            sample = int(5000 * math.sin(2 * math.pi * 220 * i / rate))
            data.extend(struct.pack("<h", sample))
        f.writeframes(bytes(data))


def test_reference_selection_without_diarization(tmp_path: Path):
    wav = tmp_path / "voice.wav"
    make_tone(wav)
    candidate = select_reference([wav])
    assert candidate.source == wav
    assert candidate.duration >= 5.5
    assert candidate.score > 0
    assert 6.9 < wav_duration(wav) < 7.1
