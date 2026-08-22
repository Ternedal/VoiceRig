from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def ensure_ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise FFmpegError("FFmpeg blev ikke fundet. Installér FFmpeg og prøv igen.")
    return exe


def extract_mono_wav(source: Path, target: Path, sample_rate: int = 24000) -> Path:
    """Decode arbitrary supported media to analysis-friendly mono PCM WAV."""
    exe = ensure_ffmpeg()
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source),
        "-vn", "-ac", "1", "-ar", str(sample_rate),
        "-c:a", "pcm_s16le", str(target),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or "ukendt FFmpeg-fejl").strip()
        raise FFmpegError(f"Kunne ikke læse {source.name}: {detail[:500]}")
    if not target.exists() or target.stat().st_size < 128:
        raise FFmpegError(f"{source.name} indeholder ingen brugbar lyd.")
    return target


def cut_wav(source: Path, target: Path, start_s: float, duration_s: float, sample_rate: int = 24000) -> Path:
    exe = ensure_ffmpeg()
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        exe, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{max(0.0, start_s):.3f}", "-t", f"{max(0.1, duration_s):.3f}",
        "-i", str(source), "-ac", "1", "-ar", str(sample_rate),
        "-c:a", "pcm_s16le", str(target),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise FFmpegError((proc.stderr or "Kunne ikke klippe reference").strip()[:500])
    return target


def stitch_wav_segments(
    source: Path,
    target: Path,
    segments: list[tuple[float, float]],
    *,
    gap_ms: int = 80,
) -> Path:
    """Join exact clean regions from one canonical mono PCM WAV.

    The gaps between diarized turns are deliberately *not* copied because they
    may contain another speaker. A tiny silence separator avoids hard sample
    discontinuities between otherwise non-contiguous utterances.
    """
    if not segments:
        raise FFmpegError("Ingen talesegmenter at samle til reference.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(source), "rb") as src:
        if src.getnchannels() != 1 or src.getsampwidth() != 2:
            raise FFmpegError("Reference-stitching kræver canonical mono PCM16 WAV.")
        rate = src.getframerate()
        if rate <= 0:
            raise FFmpegError("Reference-WAV har ugyldig sample rate.")
        silence = b"\x00\x00" * max(0, int(rate * gap_ms / 1000))
        chunks: list[bytes] = []
        total_frames = src.getnframes()
        for start_s, duration_s in segments:
            start = max(0, min(total_frames, int(max(0.0, start_s) * rate)))
            frames = max(1, int(max(0.05, duration_s) * rate))
            frames = min(frames, max(0, total_frames - start))
            if frames <= 0:
                continue
            src.setpos(start)
            raw = src.readframes(frames)
            if raw:
                chunks.append(raw)
        if not chunks:
            raise FFmpegError("De valgte talesegmenter indeholdt ingen lyd.")
        with wave.open(str(target), "wb") as dst:
            dst.setnchannels(1)
            dst.setsampwidth(2)
            dst.setframerate(rate)
            for idx, raw in enumerate(chunks):
                if idx:
                    dst.writeframes(silence)
                dst.writeframes(raw)
    if not target.exists() or target.stat().st_size < 128:
        raise FFmpegError("Den samlede reference blev tom.")
    return target


def stitch_wav_sources(
    parts: list[tuple[Path, float, float]],
    target: Path,
    *,
    gap_ms: int = 80,
) -> Path:
    """Join clean regions from multiple canonical mono PCM16 WAV files.

    VoiceRig normalizes every upload to the same 24 kHz mono PCM format before
    diarization. This helper lets several short, speaker-matched clips contribute
    to one Chatterbox reference without copying silence or other speakers between
    the selected turns.
    """
    if not parts:
        raise FFmpegError("Ingen talesegmenter at samle på tværs af klip.")

    target.parent.mkdir(parents=True, exist_ok=True)
    chunks: list[bytes] = []
    rate: int | None = None
    for source, start_s, duration_s in parts:
        with wave.open(str(source), "rb") as src:
            if src.getnchannels() != 1 or src.getsampwidth() != 2:
                raise FFmpegError("Multi-klip reference kræver canonical mono PCM16 WAV.")
            source_rate = src.getframerate()
            if source_rate <= 0:
                raise FFmpegError("Reference-WAV har ugyldig sample rate.")
            if rate is None:
                rate = source_rate
            elif source_rate != rate:
                raise FFmpegError("Referenceklippene har forskellige sample rates.")

            total_frames = src.getnframes()
            start = max(0, min(total_frames, int(max(0.0, start_s) * source_rate)))
            frames = max(1, int(max(0.05, duration_s) * source_rate))
            frames = min(frames, max(0, total_frames - start))
            if frames <= 0:
                continue
            src.setpos(start)
            raw = src.readframes(frames)
            if raw:
                chunks.append(raw)

    if not chunks or rate is None:
        raise FFmpegError("De valgte multi-klip-segmenter indeholdt ingen lyd.")

    silence = b"\x00\x00" * max(0, int(rate * gap_ms / 1000))
    with wave.open(str(target), "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(rate)
        for idx, raw in enumerate(chunks):
            if idx:
                dst.writeframes(silence)
            dst.writeframes(raw)

    if not target.exists() or target.stat().st_size < 128:
        raise FFmpegError("Den samlede multi-klip-reference blev tom.")
    return target
