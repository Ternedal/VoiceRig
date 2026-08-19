from pathlib import Path

from voicerig.analysis.diarization import DiarizationResult, Segment, Speaker, primary_speaker_segments


def test_primary_speaker_matches_across_files():
    a, b = Path("a.wav"), Path("b.wav")
    r1 = DiarizationResult(
        a,
        (Segment(0, 8, "A"), Segment(8, 10, "B")),
        (Speaker(a, "A", 8, (1.0, 0.0)), Speaker(a, "B", 2, (0.0, 1.0))),
    )
    r2 = DiarizationResult(
        b,
        (Segment(0, 7, "X"), Segment(7, 9, "Y")),
        (Speaker(b, "X", 7, (0.99, 0.01)), Speaker(b, "Y", 2, (0.0, 1.0))),
    )
    selected = primary_speaker_segments([r1, r2], similarity_threshold=0.9)
    assert [s.speaker for s in selected[a]] == ["A"]
    assert [s.speaker for s in selected[b]] == ["X"]
