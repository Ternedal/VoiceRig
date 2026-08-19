import math
import struct
import wave
from pathlib import Path

from voicerig.analysis.diarization import Segment
from voicerig.analysis.reference import select_reference, wav_duration
from voicerig.media.ffmpeg import stitch_wav_segments


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


def test_reference_can_stitch_multiple_short_turns_without_copying_gaps(tmp_path: Path):
    wav = tmp_path / "conversation.wav"
    make_tone(wav, seconds=10.0)
    segments = [
        Segment(0.0, 3.2, "A"),
        Segment(4.5, 7.7, "A"),
    ]

    candidate = select_reference([wav], {wav: segments})

    assert candidate.speaker == "A"
    assert len(candidate.parts) == 2
    assert 6.3 < candidate.duration < 6.5

    stitched = tmp_path / "stitched.wav"
    stitch_wav_segments(candidate.source, stitched, list(candidate.parts))
    # 6.4 seconds of selected speech plus one 80 ms separator. The 1.3 second
    # source gap is not copied because it may contain another speaker.
    assert 6.45 < wav_duration(stitched) < 6.55
