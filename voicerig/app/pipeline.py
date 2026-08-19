from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from voicerig.analysis.diarization import DiarizationUnavailable, diarize_many, primary_speaker_segments
from voicerig.analysis.reference import select_reference
from voicerig.engines.chatterbox import ChatterboxEngine
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


def create_voice(name: str, sources: list[Path], output_dir: Path, language: str = "da") -> BuildResult:
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
            # One subprocess/model load for all uploaded clips. The pyannote
            # environment is CPU-only and intentionally separate from the
            # CUDA/Chatterbox environment.
            results = diarize_many(wavs)
            diarizations = primary_speaker_segments(results)
            used = bool(diarizations)
        except DiarizationUnavailable:
            diarizations = {}

        candidate = select_reference(wavs, diarizations)
        reference = work / "reference.wav"
        if candidate.parts:
            stitch_wav_segments(candidate.source, reference, list(candidate.parts))
        else:
            cut_wav(candidate.source, reference, candidate.start, candidate.duration)

        engine = ChatterboxEngine(language=language)
        conditioning = work / "conditioning.pt"
        preview = work / "preview.wav"
        engine.build_conditioning(reference, conditioning)
        engine.preview(reference, preview)

        package = output_dir / f"{slugify(name)}.mrvoice"
        build_package(name, language, reference, conditioning, preview, package)

        saved_reference = output_dir / f"{slugify(name)}-reference.wav"
        shutil.copy2(reference, saved_reference)
        return BuildResult(package=package, reference=saved_reference, diarization_used=used)
