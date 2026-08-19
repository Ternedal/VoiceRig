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


def test_cross_file_matching_does_not_single_link_chain_different_speakers():
    a, b, c = Path("a.wav"), Path("b.wav"), Path("c.wav")
    # A~B and B~C are each about 0.8 cosine similarity, but C is far from the
    # duration-weighted A+B centroid. Single-link clustering would incorrectly
    # absorb all three into one identity.
    r1 = DiarizationResult(a, (Segment(0, 10, "A"),), (Speaker(a, "A", 10, (1.0, 0.0)),))
    r2 = DiarizationResult(b, (Segment(0, 9, "B"),), (Speaker(b, "B", 9, (0.8, 0.6)),))
    r3 = DiarizationResult(c, (Segment(0, 8, "C"),), (Speaker(c, "C", 8, (0.28, 0.96)),))

    selected = primary_speaker_segments([r1, r2, r3], similarity_threshold=0.75)

    assert a in selected
    assert b in selected
    assert c not in selected
