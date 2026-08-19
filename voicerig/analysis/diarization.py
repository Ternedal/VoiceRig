from __future__ import annotations

import json
import math
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


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


_MARKER = "VOICERIG_DIARIZATION_JSON="


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _worker_python() -> Path:
    explicit = os.getenv("VOICERIG_DIARIZATION_PYTHON", "").strip()
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise DiarizationUnavailable(
            f"VOICERIG_DIARIZATION_PYTHON peger på en fil der ikke findes: {candidate}"
        )

    root = _repo_root()
    candidates = [
        root / ".venv-diarization" / "Scripts" / "python.exe",
        root / ".venv-diarization" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise DiarizationUnavailable(
        "Det separate pyannote-miljø mangler. Kør setup-windows.ps1 igen."
    )


def _parse_result(item: dict) -> DiarizationResult:
    source = Path(str(item["source"])).resolve()
    segments = tuple(
        Segment(float(seg["start"]), float(seg["end"]), str(seg["speaker"]))
        for seg in item.get("segments", [])
    )
    speakers = tuple(
        Speaker(
            source=source,
            label=str(speaker["label"]),
            duration=float(speaker.get("duration", 0.0)),
            embedding=(
                tuple(float(v) for v in speaker["embedding"])
                if speaker.get("embedding") is not None
                else None
            ),
        )
        for speaker in item.get("speakers", [])
    )
    return DiarizationResult(source, segments, speakers)


def diarize_many(audios: list[Path]) -> list[DiarizationResult]:
    """Run all files through one CPU-only pyannote subprocess/model load.

    Chatterbox and current pyannote have incompatible torch requirements, so
    diarization deliberately lives in `.venv-diarization`. This also ensures
    pyannote cannot consume GPU VRAM that is reserved for voice generation.
    """
    if not audios:
        return []
    worker = Path(__file__).with_name("pyannote_worker.py")
    cmd = [str(_worker_python()), str(worker), *(str(p.resolve()) for p in audios)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(60.0, float(os.getenv("VOICERIG_DIARIZATION_TIMEOUT_SECONDS", "1800"))),
        )
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise DiarizationUnavailable(f"Speaker-analysen kunne ikke startes: {exc}") from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "ukendt pyannote-fejl").strip()
        raise DiarizationUnavailable(
            "Speaker-analyse kunne ikke gennemføres. Første opsætning kan kræve "
            f"HF_TOKEN og accept af community-1-vilkårene. {detail[:500]}"
        )

    payload_line = next(
        (line for line in reversed(proc.stdout.splitlines()) if line.startswith(_MARKER)),
        None,
    )
    if payload_line is None:
        raise DiarizationUnavailable("pyannote-worker returnerede intet gyldigt resultat.")
    try:
        raw = json.loads(payload_line[len(_MARKER):])
        results = [_parse_result(item) for item in raw]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise DiarizationUnavailable("pyannote-worker returnerede ugyldige data.") from exc
    if len(results) != len(audios):
        raise DiarizationUnavailable("pyannote-worker returnerede forkert antal resultater.")
    return results


def diarize(audio: Path) -> DiarizationResult:
    return diarize_many([audio])[0]


def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    if len(a) != len(b) or not a:
        return -1.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return -1.0
    return dot / (na * nb)


def _cluster_centroid(cluster: list[Speaker]) -> tuple[float, ...] | None:
    """Duration-weighted embedding centroid for conservative speaker matching.

    Comparing a new speaker with the cluster centroid avoids single-link
    chaining, where A can match B and B can match C even though A and C are
    clearly different people.
    """
    usable = [speaker for speaker in cluster if speaker.embedding is not None]
    if not usable:
        return None
    dims = len(usable[0].embedding or ())
    usable = [speaker for speaker in usable if len(speaker.embedding or ()) == dims]
    if not usable or dims == 0:
        return None
    weights = [max(speaker.duration, 0.001) for speaker in usable]
    total = sum(weights)
    return tuple(
        sum((speaker.embedding or ())[idx] * weight for speaker, weight in zip(usable, weights)) / total
        for idx in range(dims)
    )


def _cluster_duration(cluster: list[Speaker]) -> float:
    return sum(max(0.0, speaker.duration) for speaker in cluster)


def primary_speaker_segments(
    results: list[DiarizationResult],
    similarity_threshold: float = 0.75,
    minimum_dominance_ratio: float = 1.5,
) -> dict[Path, list[Segment]]:
    """Match speakers across files and return the clearly dominant person.

    If two distinct voice clusters have similar total speaking time, guessing is
    worse than asking for cleaner input. VoiceRig therefore auto-selects only
    when the leading cluster is at least `minimum_dominance_ratio` times the
    runner-up. A future UI can expose explicit speaker selection on this exact
    ambiguity signal without changing the clustering contract.
    """
    nodes = [speaker for result in results for speaker in result.speakers if speaker.duration > 0]
    if not nodes:
        return {}

    clusters: list[list[Speaker]] = []
    for node in sorted(nodes, key=lambda s: s.duration, reverse=True):
        best_idx = None
        best_score = similarity_threshold
        if node.embedding is not None:
            for idx, cluster in enumerate(clusters):
                centroid = _cluster_centroid(cluster)
                if centroid is None:
                    continue
                score = _cosine(node.embedding, centroid)
                if score >= best_score:
                    best_score, best_idx = score, idx
        if best_idx is None:
            clusters.append([node])
        else:
            clusters[best_idx].append(node)

    ranked = sorted(clusters, key=_cluster_duration, reverse=True)
    primary = ranked[0]
    if len(ranked) > 1:
        first = _cluster_duration(ranked[0])
        second = _cluster_duration(ranked[1])
        if second > 0.0 and first / second < max(1.0, minimum_dominance_ratio):
            raise ValueError(
                "Vi fandt flere omtrent lige tydelige stemmer i klippene. "
                "Tilføj et klip med mere tale fra den person, du vil bruge, "
                "eller fjern et klip hvor en anden person fylder meget."
            )

    selected = {(s.source, s.label) for s in primary}
    by_source: dict[Path, list[Segment]] = {}
    for result in results:
        matches = [seg for seg in result.segments if (result.source, seg.speaker) in selected]
        if matches:
            by_source[result.source] = matches
    return by_source
