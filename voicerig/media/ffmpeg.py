from __future__ import annotations

import shutil
import subprocess
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
