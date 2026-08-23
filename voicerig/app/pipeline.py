from __future__ import annotations

import base64
import math
import shutil
import tempfile
import threading
from collections.abc import Callable
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
from voicerig.analysis.reference import ReferenceCandidate, rank_references
from voicerig.config import allow_undiarized_fallback
from voicerig.engines.catalog import CURRENT_ENGINE, ROST_DANISH_ENGINE_SPEC, EngineSpec
from voicerig.engines.chatterbox import ChatterboxEngine
from voicerig.engines.rost import build_rost_danish_artifacts
from voicerig.media.audio import validate_wav
from voicerig.media.ffmpeg import (
    cut_wav,
    extract_mono_wav,
    stitch_wav_segments,
    stitch_wav_sources,
)
from voicerig.profiles.package import build_package, slugify


SUPPORTED_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v",
    ".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma",
}
MAX_SOURCE_FILES = 20
MAX_REFERENCE_CHOICES = 4

ProgressCallback = Callable[[str, int, str], None]
_BUILD_GATE = threading.Lock()


@dataclass(frozen=True)
class BuildResult:
    package: Path
    reference: Path
    diarization_used: bool


class VoiceBuildBusy(RuntimeError):
    pass


class SpeakerSelectionRequired(ValueError):
    def __init__(self, choices: list[dict]):
        super().__init__("Vi fandt flere tydelige stemmer. Vælg den, du vil bruge.")
        self.choices = choices


class ReferenceSelectionRequired(ValueError):
    def __init__(self, choices: list[dict]):
        super().__init__(
            "Vi fandt flere gode referenceklip. Lyt til de danske prøver og vælg den, der lyder mest som dig."
        )
        self.choices = choices


def build_gate_status() -> dict:
    return {"busy": _BUILD_GATE.locked()}


def _progress(callback: ProgressCallback | None, stage: str, percent: int, message: str) -> None:
    if callback is not None:
        callback(stage, max(0, min(100, int(percent))), message)


def _acquire_build_gate(progress: ProgressCallback | None, wait: bool) -> None:
    if not wait:
        if not _BUILD_GATE.acquire(blocking=False):
            raise VoiceBuildBusy("VoiceRig arbejder allerede på en stemme.")
        return
    while not _BUILD_GATE.acquire(timeout=0.25):
        _progress(progress, "queued", 0, "Venter på VoiceRig build-køen…")


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


def _speaker_anchor(wavs: list[Path], source: Path, segments) -> str:
    try:
        source_index = wavs.index(source)
    except ValueError as exc:
        raise ValueError("Speaker-preview peger på en ukendt inputfil.") from exc
    anchor_segment = max(segments, key=lambda item: item.duration)
    midpoint = anchor_segment.start + anchor_segment.duration / 2.0
    return f"{source_index}:{midpoint:.3f}"


def _cluster_from_anchor(
    wavs: list[Path],
    results: list[DiarizationResult],
    clusters: tuple[SpeakerCluster, ...],
    anchor: str,
) -> SpeakerCluster:
    try:
        raw_index, raw_time = anchor.split(":", 1)
        source_index = int(raw_index)
        timestamp = float(raw_time)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("Stemmevalget er ugyldigt. Vælg stemmen igen.") from exc
    if source_index < 0 or source_index >= len(wavs) or not math.isfinite(timestamp) or timestamp < 0.0:
        raise ValueError("Stemmevalget er ugyldigt. Vælg stemmen igen.")

    target = wavs[source_index]
    matches: list[SpeakerCluster] = []
    for cluster in clusters:
        segments = segments_for_cluster(results, cluster).get(target, [])
        if any(segment.start - 0.15 <= timestamp <= segment.end + 0.15 for segment in segments):
            matches.append(cluster)
    if len(matches) != 1:
        raise ValueError("VoiceRig kunne ikke genfinde den valgte stemme sikkert. Vælg stemmen igen.")
    return matches[0]


def _speaker_choices(
    work: Path,
    wavs: list[Path],
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
                "anchor": _speaker_anchor(wavs, source, segments),
                "label": f"Stemme {choice}",
                "speech_seconds": round(cluster.duration, 1),
                "preview_duration": info["duration"],
                "preview_wav_base64": base64.b64encode(preview.read_bytes()).decode("ascii"),
            }
        )
    return choices


def _materialize_reference(candidate: ReferenceCandidate, target: Path) -> Path:
    if candidate.source_parts:
        stitch_wav_sources(list(candidate.source_parts), target)
    elif candidate.parts:
        stitch_wav_segments(candidate.source, target, list(candidate.parts))
    else:
        cut_wav(candidate.source, target, candidate.start, candidate.duration)
    validate_wav(target, min_duration_s=5.4, max_duration_s=11.5, require_audible=True)
    return target


def _reference_source_count(candidate: ReferenceCandidate) -> int:
    if candidate.source_parts:
        return len({source for source, _start, _duration in candidate.source_parts})
    return 1


def _is_danish(language: str) -> bool:
    return str(language or "").strip().lower().split("-", 1)[0] == "da"


def _build_engine_spec(language: str) -> EngineSpec:
    """Return the production engine used for newly built profiles.

    RC22-RC24 physical acceptance established Røst as the preferred Danish
    engine. Keep the existing multilingual Chatterbox path for other languages
    rather than silently extending the Danish decision beyond its evidence.
    """
    return ROST_DANISH_ENGINE_SPEC if _is_danish(language) else CURRENT_ENGINE


def _build_artifacts_for_language(
    reference: Path,
    conditioning: Path,
    preview: Path,
    language: str,
) -> tuple[Path, Path]:
    spec = _build_engine_spec(language)
    if spec.identity == ROST_DANISH_ENGINE_SPEC.identity:
        return build_rost_danish_artifacts(reference, conditioning, preview)
    return ChatterboxEngine(language=language).build_artifacts(reference, conditioning, preview)


def _reference_choices(
    work: Path,
    ranked: list[ReferenceCandidate],
    language: str,
    progress: ProgressCallback | None,
) -> list[dict]:
    """Render auditions with the same engine the final profile will use.

    Raw source/reference audio is never exposed through the job API. For Danish
    profiles this is now deliberately Røst-aware: RC23 physically proved that a
    reference selected through the old general Chatterbox audition could be
    worse for Røst identity. The user therefore hears the actual production
    engine before choosing the authoritative reference.
    """
    spec = _build_engine_spec(language)
    choices: list[dict] = []
    total = min(MAX_REFERENCE_CHOICES, len(ranked))
    for idx, candidate in enumerate(ranked[:MAX_REFERENCE_CHOICES], start=1):
        _progress(
            progress,
            "reference_audition",
            55 + int(((idx - 1) / max(1, total)) * 10),
            f"Laver {spec.label}-prøve {idx} af {total}…",
        )
        reference = _materialize_reference(candidate, work / f"reference-choice-{idx:02d}.wav")
        conditioning = work / f"conditioning-choice-{idx:02d}.pt"
        preview = work / f"preview-choice-{idx:02d}.wav"
        _build_artifacts_for_language(reference, conditioning, preview, language)
        info = validate_wav(preview, min_duration_s=0.5, max_duration_s=90.0, require_audible=True)
        choices.append(
            {
                "choice": idx,
                "label": f"Reference {idx}",
                "engine": spec.name,
                "engine_label": spec.label,
                "quality_score": round(float(candidate.score), 4),
                "reference_seconds": round(float(candidate.duration), 1),
                "source_clip_count": _reference_source_count(candidate),
                "preview_duration": info["duration"],
                "preview_wav_base64": base64.b64encode(preview.read_bytes()).decode("ascii"),
            }
        )
    return choices


def _create_voice_impl(
    name: str,
    sources: list[Path],
    output_dir: Path,
    language: str,
    speaker_choice: int | None,
    speaker_anchor: str | None,
    reference_choice: int | None,
    progress: ProgressCallback | None,
) -> BuildResult:
    _progress(progress, "starting", 1, "Forbereder voice-build…")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="voicerig-") as tmp:
        work = Path(tmp)
        wavs: list[Path] = []
        total_sources = len(sources)
        for idx, source in enumerate(sources):
            _progress(progress, "decoding", 5 + int((idx / max(1, total_sources)) * 15), f"Normaliserer klip {idx + 1} af {total_sources}…")
            wav = work / f"source_{idx:02d}.wav"
            extract_mono_wav(source, wav)
            wavs.append(wav)
        _progress(progress, "decoding", 20, "Lyd og video er normaliseret.")

        diarizations = {}
        used = False
        try:
            _progress(progress, "diarization", 26, "Finder og matcher speakers…")
            results = diarize_many(wavs)
            clusters = speaker_clusters(results)
            try:
                if speaker_anchor:
                    _progress(progress, "speaker_selection", 42, "Genfinder den valgte speaker…")
                    chosen = _cluster_from_anchor(wavs, results, clusters, speaker_anchor)
                    diarizations = segments_for_cluster(results, chosen)
                else:
                    diarizations = primary_speaker_segments(results, speaker_choice=speaker_choice)
            except AmbiguousSpeakers as exc:
                choices = _speaker_choices(work, wavs, results, clusters)
                if len(choices) >= 2:
                    _progress(progress, "speaker_selection", 40, "Venter på valg mellem flere tydelige speakers.")
                    raise SpeakerSelectionRequired(choices) from exc
                raise ValueError("Vi fandt flere stemmer, men kunne ikke lave tydelige stemmeprøver. Tilføj et klip med lidt mere ren tale.") from exc
            used = bool(diarizations)
            if not used and not allow_undiarized_fallback():
                raise DiarizationUnavailable("Speaker-analysen fandt ingen brugbar stemmeidentitet i materialet.")
        except SpeakerSelectionRequired:
            raise
        except DiarizationUnavailable as exc:
            if not allow_undiarized_fallback():
                raise RuntimeError(
                    "VoiceRig kunne ikke udføre sikker speaker-analyse. Kontrollér HF_TOKEN, community-1-modeladgang og den separate "
                    f"diarization-runtime. Detalje: {exc}"
                ) from exc
            diarizations = {}
        _progress(progress, "reference", 50, "Vælger de bedste rene talestykker på tværs af klippene…")

        ranked = rank_references(wavs, diarizations, limit=MAX_REFERENCE_CHOICES)
        if reference_choice is None and len(ranked) >= 2:
            choices = _reference_choices(work, ranked, language, progress)
            if len(choices) >= 2:
                _progress(progress, "reference_selection", 65, "Venter på dit valg af den bedste prøve fra produktionsmotoren.")
                raise ReferenceSelectionRequired(choices)

        if reference_choice is None:
            selected_index = 0
        else:
            selected_index = int(reference_choice) - 1
            if selected_index < 0 or selected_index >= len(ranked):
                raise ValueError("Den valgte reference findes ikke længere. Start voice-build igen.")

        reference = _materialize_reference(ranked[selected_index], work / "reference.wav")
        alternatives: list[Path] = []
        backup_candidates = [candidate for idx, candidate in enumerate(ranked) if idx != selected_index]
        for idx, candidate in enumerate(backup_candidates[:3], start=1):
            target = work / f"reference-alt-{idx:02d}.wav"
            alternatives.append(_materialize_reference(candidate, target))

        spec = _build_engine_spec(language)
        _progress(progress, "conditioning", 70, f"Bygger stemmens {spec.label}-conditioning og preview…")
        conditioning = work / "conditioning.pt"
        preview = work / "preview.wav"
        _build_artifacts_for_language(reference, conditioning, preview, language)
        validate_wav(preview, min_duration_s=0.5, max_duration_s=90.0, require_audible=True)

        _progress(progress, "packaging", 90, "Pakker og validerer .mrvoice…")
        package = output_dir / f"{slugify(name)}.mrvoice"
        build_package(
            name,
            language,
            reference,
            conditioning,
            preview,
            package,
            alternatives=alternatives,
            engine_spec=spec,
        )

        saved_reference = output_dir / f"{slugify(name)}-reference.wav"
        shutil.copy2(reference, saved_reference)
        _progress(progress, "complete", 100, f"Stemmen er bygget og valideret med {spec.label}.")
        return BuildResult(package=package, reference=saved_reference, diarization_used=used)


def create_voice(
    name: str,
    sources: list[Path],
    output_dir: Path,
    language: str = "da",
    speaker_choice: int | None = None,
    speaker_anchor: str | None = None,
    reference_choice: int | None = 1,
    progress: ProgressCallback | None = None,
    wait_for_build_slot: bool = True,
) -> BuildResult:
    if not name.strip():
        raise ValueError("Stemmen skal have et navn.")
    if not sources:
        raise ValueError("Tilføj mindst én lyd- eller videofil.")
    if len(sources) > MAX_SOURCE_FILES:
        raise ValueError(f"Maksimalt {MAX_SOURCE_FILES} filer pr. stemme.")
    bad = [p.name for p in sources if p.suffix.lower() not in SUPPORTED_EXTENSIONS]
    if bad:
        raise ValueError(f"Ikke-understøttet filtype: {', '.join(bad)}")

    _acquire_build_gate(progress, wait_for_build_slot)
    try:
        return _create_voice_impl(
            name,
            sources,
            output_dir,
            language,
            speaker_choice,
            speaker_anchor,
            reference_choice,
            progress,
        )
    finally:
        _BUILD_GATE.release()
