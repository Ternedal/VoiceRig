from __future__ import annotations

import base64
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from voicerig.analysis.diarization import (
    AmbiguousSpeakers,
    DiarizationResult,
    DiarizationUnavailable,
    SpeakerCluster,
    diarize_many,
    primary_speaker_segments,
    segments_for_cluster,
    speaker_clusters,
)
from voicerig.analysis.reference import select_reference
from voicerig.config import allow_undiarized_fallback
from voicerig.engines.chatterbox import ChatterboxEngine
from voicerig.media.audio import validate_wav
from voicerig.media.ffmpeg import cut_wav, extract_mono_wav, stitch_wav_segments
from voicerig.profiles.package import build_package, slugify


SUPPORTED_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v",
    ".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
}


@dataclass(frozen=True)
class BuildResult:
    package: Path
    reference: Path
    diarization_used: bool


class SpeakerSelectionRequired(ValueError):
    def __init__(self, choices: list[dict]):
        super().__init__("Vi fandt flere tydelige stemmer. Vælg den, du vil bruge.")
        self.choices = choices


def _preview_parts(segments, target_s: float = 4.0) -> list[tuple[float, float]]:
    selected: list[tuple[float, float]] = []
    remaining = target_s
    for segment in sorted(segments, key=lambda item: item.duration, reverse=True):
        if segment.duration < 0.4 or remaining <= 0.0:
            continue
        take = min(segment.duration, remaining)
        selected.append((segment.start, take))
        remaining -= take
    selected.sort(key=lambda item: item[0])
    return selected


def _speaker_choices(
    work: Path,
    results: list[DiarizationResult],
    clusters: tuple[SpeakerCluster, ...],
) -> list[dict]:
    choices: list[dict] = []
    for choice, cluster in enumerate(clusters[:4], start=1):
        if cluster.duration < 0.8:
            continue
        by_source = segments_for_cluster(results, cluster)
        if not by_source:
            continue
        source, segments = max(
            by_source.items(),
            key=lambda item: sum(segment.duration for segment in item[1]),
        )
        parts = _preview_parts(segments)
        if not parts:
            continue
        preview = work / f"speaker-choice-{choice}.wav"
        stitch_wav_segments(source, preview, parts, gap_ms=80)
        try:
            info = validate_wav(preview, min_duration_s=0.35, max_duration_s=5.0, require_audible=True)
        except RuntimeError:
            continue
        choices.append(
            {
                "choice": choice,
                "label": f"Stemme {choice}",
                "speech_seconds": round(cluster.duration, 1),
                "preview_duration": info["duration"],
                "preview_wav_base64": base64.b64encode(preview.read_bytes()).decode("ascii"),
            }
        )
    return choices


def create_voice(
    name: str,
    sources: list[Path],
    output_dir: Path,
    language: str = "da",
    speaker_choice: int | None = None,
) -> BuildResult:
    if not name.strip():
        raise ValueError("Stemmen skal have et navn.")
    if not sources:
        raise ValueError("Tilføj mindst én lyd- eller videofil.")
    bad = [p.name for p in sources if p.suffix.lower() not in SUPPORTED_EXTENSIONS]
    if bad:
        raise ValueError(f"Ikke-understøttet filtype: {', '.join(bad)}")

    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voicerig-") as tmp:
        work = Path(tmp)
        wavs: list[Path] = []
        for idx, source in enumerate(sources):
            wav = work / f"source_{idx:02d}.wav"
            extract_mono_wav(source, wav)
            wavs.append(wav)

        diarizations = {}
        used = False
        try:
            results = diarize_many(wavs)
            try:
                diarizations = primary_speaker_segments(
                    results,
                    speaker_choice=speaker_choice,
                )
            except AmbiguousSpeakers as exc:
                clusters = speaker_clusters(results)
                choices = _speaker_choices(work, results, clusters)
                if len(choices) >= 2:
                    raise SpeakerSelectionRequired(choices) from exc
                raise ValueError(
                    "Vi fandt flere stemmer, men kunne ikke lave tydelige stemmeprøver. "
                    "Tilføj et klip med lidt mere ren tale."
                ) from exc
            used = bool(diarizations)
            if not used and not allow_undiarized_fallback():
                raise DiarizationUnavailable(
                    "Speaker-analysen fandt ingen brugbar stemmeidentitet i materialet."
                )
        except SpeakerSelectionRequired:
            raise
        except DiarizationUnavailable as exc:
            if not allow_undiarized_fallback():
                raise RuntimeError(
                    "VoiceRig kunne ikke udføre sikker speaker-analyse. "
                    "Kontrollér HF_TOKEN, community-1-modeladgang og den separate "
                    f"diarization-runtime. Detalje: {exc}"
                ) from exc
            diarizations = {}

        candidate = select_reference(wavs, diarizations)
        reference = work / "reference.wav"
        if candidate.parts:
            stitch_wav_segments(candidate.source, reference, list(candidate.parts))
        else:
            cut_wav(candidate.source, reference, candidate.start, candidate.duration)
        validate_wav(reference, min_duration_s=5.4, max_duration_s=11.5, require_audible=True)

        engine = ChatterboxEngine(language=language)
        conditioning = work / "conditioning.pt"
        preview = work / "preview.wav"
        engine.build_artifacts(reference, conditioning, preview)
        validate_wav(preview, min_duration_s=0.5, max_duration_s=90.0, require_audible=True)

        package = output_dir / f"{slugify(name)}.mrvoice"
        build_package(name, language, reference, conditioning, preview, package)

        saved_reference = output_dir / f"{slugify(name)}-reference.wav"
        shutil.copy2(reference, saved_reference)
        return BuildResult(package=package, reference=saved_reference, diarization_used=used)
