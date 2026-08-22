from __future__ import annotations

import math
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

from .diarization import Segment


SourcePart = tuple[Path, float, float]


@dataclass(frozen=True)
class ReferenceCandidate:
    source: Path
    start: float
    duration: float
    score: float
    speaker: str | None = None
    parts: tuple[tuple[float, float], ...] = ()
    source_parts: tuple[SourcePart, ...] = ()


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as f:
        rate = f.getframerate()
        return f.getnframes() / rate if rate else 0.0


def _window_quality(path: Path, start_s: float, duration_s: float) -> float:
    """Cheap deterministic signal score: reward audible, non-clipped speech-like audio."""
    with wave.open(str(path), "rb") as f:
        if f.getsampwidth() != 2 or f.getnchannels() != 1:
            return 0.0
        rate = f.getframerate()
        f.setpos(min(f.getnframes(), int(start_s * rate)))
        raw = f.readframes(max(1, int(duration_s * rate)))
    if len(raw) < 2:
        return 0.0
    count = len(raw) // 2
    samples = struct.unpack("<" + "h" * count, raw[: count * 2])
    if not samples:
        return 0.0
    peak = max(abs(x) for x in samples) / 32768.0
    rms = math.sqrt(sum(float(x) * float(x) for x in samples) / len(samples)) / 32768.0
    clipped = sum(1 for x in samples if abs(x) >= 32700) / len(samples)
    audible = min(1.0, rms / 0.08)
    headroom = max(0.0, 1.0 - max(0.0, peak - 0.95) * 10.0)
    clip_penalty = max(0.0, 1.0 - clipped * 20.0)
    return round(audible * headroom * clip_penalty, 4)


def _stitched_candidate(
    wav: Path,
    speaker: str,
    segments: list[Segment],
    target_s: float,
) -> ReferenceCandidate | None:
    scored: list[tuple[Segment, float]] = []
    for seg in segments:
        if seg.duration < 0.8:
            continue
        scored.append((seg, _window_quality(wav, seg.start, seg.duration)))
    if sum(seg.duration for seg, _score in scored) < 5.5:
        return None

    selected: list[tuple[float, float, float]] = []
    speech_s = 0.0
    weighted_quality = 0.0
    for seg, quality in sorted(scored, key=lambda item: item[1], reverse=True):
        remaining = target_s - speech_s
        if remaining <= 0.0:
            break
        take = min(seg.duration, remaining)
        selected.append((seg.start, take, quality))
        speech_s += take
        weighted_quality += quality * take
    if speech_s < 5.5:
        return None

    selected.sort(key=lambda item: item[0])
    parts = tuple((start, duration) for start, duration, _quality in selected)
    quality = weighted_quality / speech_s if speech_s else 0.0
    stitch_penalty = 0.98 if len(parts) > 1 else 1.0
    score = quality * min(1.0, speech_s / target_s) * stitch_penalty
    return ReferenceCandidate(
        wav,
        parts[0][0],
        speech_s,
        round(score, 4),
        speaker,
        parts if len(parts) > 1 else (),
    )


def _all_candidates(
    wavs: list[Path],
    diarizations: dict[Path, list[Segment]],
    target_s: float,
) -> list[ReferenceCandidate]:
    candidates: list[ReferenceCandidate] = []
    for wav in wavs:
        segments = diarizations.get(wav) or []
        if segments:
            totals: dict[str, float] = {}
            for seg in segments:
                totals[seg.speaker] = totals.get(seg.speaker, 0.0) + seg.duration
            speaker = max(totals, key=totals.get)
            speaker_segments = [s for s in segments if s.speaker == speaker]
            for seg in speaker_segments:
                if seg.duration < 5.5:
                    continue
                dur = min(target_s, seg.duration)
                score = _window_quality(wav, seg.start, dur)
                score *= min(1.0, dur / target_s)
                candidates.append(ReferenceCandidate(wav, seg.start, dur, score, speaker))
            stitched = _stitched_candidate(wav, speaker, speaker_segments, target_s)
            if stitched is not None:
                candidates.append(stitched)
        else:
            total = wav_duration(wav)
            if total < 5.5:
                continue
            dur = min(target_s, total)
            step = max(2.0, dur / 2.0)
            pos = 0.0
            while pos + 5.5 <= total:
                actual = min(dur, total - pos)
                if actual < 5.5:
                    break
                score = _window_quality(wav, pos, actual) * min(1.0, actual / target_s)
                candidates.append(ReferenceCandidate(wav, pos, actual, score, None))
                pos += step
    return candidates


def _pooled_candidates(
    diarizations: dict[Path, list[Segment]],
    target_s: float,
    limit: int,
) -> list[ReferenceCandidate]:
    """Build non-overlapping reference candidates from short turns across files.

    The diarization mapping already contains only the selected speaker's turns.
    Pooling therefore lets several short clean uploads contribute to Chatterbox
    without reintroducing speech from other speakers. We only pool when at least
    5.5 seconds of selected-speaker speech exists in total.
    """
    pieces: list[dict] = []
    for wav, segments in diarizations.items():
        for seg in segments:
            if seg.duration < 0.8:
                continue
            pieces.append(
                {
                    "source": wav,
                    "start": float(seg.start),
                    "duration": float(seg.duration),
                    "quality": float(_window_quality(wav, seg.start, seg.duration)),
                }
            )

    total_s = sum(piece["duration"] for piece in pieces)
    bundle_count = min(max(1, int(limit)), int(total_s // 5.5))
    if not pieces or bundle_count < 1:
        return []

    # Divide the available clean speech fairly enough that 11 seconds can form
    # two useful auditions instead of one 10-second audition plus an unusable
    # one-second remainder.
    bundle_target = min(float(target_s), total_s / bundle_count)
    available = [dict(piece) for piece in sorted(pieces, key=lambda item: item["quality"], reverse=True)]
    candidates: list[ReferenceCandidate] = []

    for _bundle_index in range(bundle_count):
        remaining = bundle_target
        chosen: list[tuple[Path, float, float, float]] = []
        used_sources: set[Path] = set()

        # First pass prefers contributions from different source files. Cap each
        # source at half the target while diversity is possible.
        while remaining > 0.05:
            options = [
                piece for piece in available
                if piece["duration"] >= 0.4 and piece["source"] not in used_sources
            ]
            if not options:
                break
            piece = max(options, key=lambda item: item["quality"])
            take_cap = max(0.8, bundle_target / 2.0)
            take = min(piece["duration"], remaining, take_cap)
            if take < 0.4:
                break
            chosen.append((piece["source"], piece["start"], take, piece["quality"]))
            used_sources.add(piece["source"])
            piece["start"] += take
            piece["duration"] -= take
            remaining -= take

        # Then fill the rest with the best remaining clean speech, even if it
        # comes from a source already represented in this bundle.
        while remaining > 0.05:
            options = [piece for piece in available if piece["duration"] >= 0.4]
            if not options:
                break
            piece = max(options, key=lambda item: item["quality"])
            take = min(piece["duration"], remaining)
            if take < 0.4:
                break
            chosen.append((piece["source"], piece["start"], take, piece["quality"]))
            piece["start"] += take
            piece["duration"] -= take
            remaining -= take

        duration = sum(part[2] for part in chosen)
        if duration < 5.5:
            break
        weighted_quality = sum(part[2] * part[3] for part in chosen) / duration
        stitch_penalty = 0.97 if len(chosen) > 1 else 1.0
        score = weighted_quality * min(1.0, duration / target_s) * stitch_penalty
        source_parts = tuple((part[0], part[1], part[2]) for part in chosen)
        candidates.append(
            ReferenceCandidate(
                source=source_parts[0][0],
                start=source_parts[0][1],
                duration=duration,
                score=round(score, 4),
                speaker="pooled",
                source_parts=source_parts,
            )
        )

    return candidates


def _candidate_source_parts(candidate: ReferenceCandidate) -> tuple[SourcePart, ...]:
    if candidate.source_parts:
        return candidate.source_parts
    parts = candidate.parts or ((candidate.start, candidate.duration),)
    return tuple((candidate.source, start, duration) for start, duration in parts)


def _overlap_ratio(a: ReferenceCandidate, b: ReferenceCandidate) -> float:
    parts_a = _candidate_source_parts(a)
    parts_b = _candidate_source_parts(b)
    overlap = 0.0
    for source_a, start_a, duration_a in parts_a:
        end_a = start_a + duration_a
        for source_b, start_b, duration_b in parts_b:
            if source_a != source_b:
                continue
            end_b = start_b + duration_b
            overlap += max(0.0, min(end_a, end_b) - max(start_a, start_b))
    denominator = min(
        sum(duration for _source, _start, duration in parts_a),
        sum(duration for _source, _start, duration in parts_b),
    )
    return overlap / denominator if denominator > 0.0 else 1.0


def rank_references(
    wavs: list[Path],
    diarizations: dict[Path, list[Segment]] | None = None,
    target_s: float = 10.0,
    limit: int = 4,
    max_overlap_ratio: float = 0.5,
) -> list[ReferenceCandidate]:
    """Return strong, non-duplicate references while preferring source diversity.

    First prefer one self-contained reference from each source file. If short
    selected-speaker turns across several files do not individually reach the
    minimum reference duration, add pooled cross-file candidates before filling
    remaining slots with extra windows from already represented files.
    """
    diarized = diarizations or {}
    candidates = sorted(
        _all_candidates(wavs, diarized, target_s),
        key=lambda item: item.score,
        reverse=True,
    )
    pooled = _pooled_candidates(diarized, target_s, limit)
    if not candidates and not pooled:
        raise ValueError("Der er for lidt brugbar tale. Tilføj mindst ca. 6-10 sekunders tydelig tale.")

    wanted = max(1, limit)
    selected: list[ReferenceCandidate] = []
    used_sources: set[Path] = set()

    # Strongest self-contained candidate from each file first.
    for candidate in candidates:
        if candidate.source in used_sources:
            continue
        if all(_overlap_ratio(candidate, existing) <= max_overlap_ratio for existing in selected):
            selected.append(candidate)
            used_sources.add(candidate.source)
        if len(selected) >= wanted:
            return selected

    # Then use pooled clean speech across files. This is the important fallback
    # for users who provide many short but individually sub-5.5-second clips.
    for candidate in pooled:
        if all(_overlap_ratio(candidate, existing) <= max_overlap_ratio for existing in selected):
            selected.append(candidate)
        if len(selected) >= wanted:
            return selected

    # Finally fill any remaining slots with diverse windows from sources already
    # represented above.
    for candidate in candidates:
        if candidate in selected:
            continue
        if all(_overlap_ratio(candidate, existing) <= max_overlap_ratio for existing in selected):
            selected.append(candidate)
        if len(selected) >= wanted:
            break
    return selected or pooled[:1] or [candidates[0]]


def select_reference(
    wavs: list[Path],
    diarizations: dict[Path, list[Segment]] | None = None,
    target_s: float = 10.0,
) -> ReferenceCandidate:
    return rank_references(wavs, diarizations, target_s=target_s, limit=1)[0]
