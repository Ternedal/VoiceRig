from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from voicerig.runtime import diarization_device


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    speaker: str

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)


@dataclass(frozen=True)
class Speaker:
    source: Path
    label: str
    duration: float
    embedding: tuple[float, ...] | None


@dataclass(frozen=True)
class DiarizationResult:
    source: Path
    segments: tuple[Segment, ...]
    speakers: tuple[Speaker, ...]


class DiarizationUnavailable(RuntimeError):
    pass


_PIPELINES: dict[str, object] = {}
_PIPELINE_LOAD_LOCK = threading.Lock()
_PIPELINE_RUN_LOCK = threading.Lock()


def _get_pipeline():
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    try:
        import torch
        from pyannote.audio import Pipeline
    except Exception as exc:  # pragma: no cover - optional heavyweight dependency
        raise DiarizationUnavailable(
            "pyannote.audio er ikke installeret. Kør: pip install -e '.[voice]'"
        ) from exc

    device = diarization_device()
    with _PIPELINE_LOAD_LOCK:
        if device in _PIPELINES:
            return _PIPELINES[device]
        try:
            pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-community-1",
                token=token,
            )
            if device == "cuda":
                pipeline.to(torch.device("cuda"))
            _PIPELINES[device] = pipeline
            return pipeline
        except Exception as exc:  # pragma: no cover - model/runtime specific
            raise DiarizationUnavailable(
                "Speaker-analyse kunne ikke startes. Første opsætning kan kræve HF_TOKEN "
                "og accept af pyannote community-1 modelvilkårene."
            ) from exc


def diarize(audio: Path) -> DiarizationResult:
    """Run local community-1 diarization and retain speaker embeddings.

    CPU is the default on purpose so the single GPU remains available for
    Chatterbox. The pipeline is cached across files and serialized because it is
    expensive shared model state.
    """
    pipeline = _get_pipeline()
    try:
        with _PIPELINE_RUN_LOCK:
            output = pipeline(str(audio))
    except Exception as exc:  # pragma: no cover - model/runtime specific
        raise DiarizationUnavailable("Speaker-analysen fejlede under kørsel.") from exc

    timeline = getattr(output, "exclusive_speaker_diarization", None)
    if timeline is None:
        timeline = output.speaker_diarization

    segments = tuple(
        Segment(float(turn.start), float(turn.end), str(speaker))
        for turn, speaker in timeline
    )
    totals: dict[str, float] = {}
    for seg in segments:
        totals[seg.speaker] = totals.get(seg.speaker, 0.0) + seg.duration

    labels = list(output.speaker_diarization.labels())
    raw_embeddings = getattr(output, "speaker_embeddings", None)
    speakers: list[Speaker] = []
    for idx, label in enumerate(labels):
        embedding = None
        if raw_embeddings is not None and idx < len(raw_embeddings):
            values = raw_embeddings[idx]
            embedding = tuple(float(v) for v in values)
        speakers.append(Speaker(audio, str(label), totals.get(str(label), 0.0), embedding))

    return DiarizationResult(audio, segments, tuple(speakers))


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if len(a) != len(b) or not a:
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return dot / (na * nb)


def primary_speaker_segments(
    results: list[DiarizationResult],
    similarity_threshold: float = 0.75,
) -> dict[Path, list[Segment]]:
    """Match speakers across files and return segments for the dominant person."""
    nodes = [speaker for result in results for speaker in result.speakers if speaker.duration > 0]
    if not nodes:
        return {}

    clusters: list[list[Speaker]] = []
    for node in sorted(nodes, key=lambda s: s.duration, reverse=True):
        best_idx = None
        best_score = similarity_threshold
        if node.embedding is not None:
            for idx, cluster in enumerate(clusters):
                candidates = [s for s in cluster if s.embedding is not None]
                if not candidates:
                    continue
                score = max(_cosine(node.embedding, s.embedding) for s in candidates)
                if score >= best_score:
                    best_score, best_idx = score, idx
        if best_idx is None:
            clusters.append([node])
        else:
            clusters[best_idx].append(node)

    primary = max(clusters, key=lambda c: sum(s.duration for s in c))
    selected = {(s.source, s.label) for s in primary}
    by_source: dict[Path, list[Segment]] = {}
    for result in results:
        matches = [seg for seg in result.segments if (result.source, seg.speaker) in selected]
        if matches:
            by_source[result.source] = matches
    return by_source
