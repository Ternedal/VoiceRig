import math
import struct
import wave
from pathlib import Path

from voicerig.analysis.diarization import Segment
from voicerig.analysis.reference import rank_references, select_reference, wav_duration
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
    assert 6.45 < wav_duration(stitched) < 6.55


def test_backup_references_prefer_diverse_non_duplicate_windows(tmp_path: Path):
    wav = tmp_path / "long-voice.wav"
    make_tone(wav, seconds=30.0)

    ranked = rank_references([wav], limit=4, max_overlap_ratio=0.5)

    assert len(ranked) >= 3
    assert ranked[0].score >= ranked[-1].score
    starts = [round(candidate.start, 1) for candidate in ranked]
    assert len(starts) == len(set(starts))
    # Ten-second candidates may overlap by at most half; exact near-duplicates
    # from the sliding window must not fill the backup slots.
    for idx, candidate in enumerate(ranked):
        for other in ranked[idx + 1:]:
            if candidate.source != other.source:
                continue
            a0, a1 = candidate.start, candidate.start + candidate.duration
            b0, b1 = other.start, other.start + other.duration
            overlap = max(0.0, min(a1, b1) - max(a0, b0))
            assert overlap / min(candidate.duration, other.duration) <= 0.5 + 1e-9


def test_multiple_source_files_are_represented_before_extra_windows(tmp_path: Path):
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    third = tmp_path / "third.wav"
    make_tone(first, seconds=30.0)
    make_tone(second, seconds=12.0)
    make_tone(third, seconds=12.0)

    ranked = rank_references([first, second, third], limit=4)

    assert len(ranked) == 4
    assert {candidate.source for candidate in ranked[:3]} == {first, second, third}
    assert ranked[3].source in {first, second, third}
