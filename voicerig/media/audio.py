from __future__ import annotations

import math
import struct
import wave
from pathlib import Path


class AudioValidationError(RuntimeError):
    pass


def validate_wav(
    path: Path,
    *,
    min_duration_s: float = 0.25,
    max_duration_s: float = 120.0,
    require_audible: bool = True,
) -> dict:
    """Validate a generated/reference WAV without loading the whole file in RAM."""
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            width = wav.getsampwidth()
            rate = wav.getframerate()
            frames = wav.getnframes()
            if channels <= 0 or rate <= 0 or frames <= 0:
                raise AudioValidationError(f"{path.name} har ugyldige WAV-egenskaber.")
            duration = frames / rate
            if duration < min_duration_s:
                raise AudioValidationError(
                    f"{path.name} er for kort ({duration:.2f}s; minimum {min_duration_s:.2f}s)."
                )
            if duration > max_duration_s:
                raise AudioValidationError(
                    f"{path.name} er for lang ({duration:.2f}s; maksimum {max_duration_s:.2f}s)."
                )

            rms = None
            if require_audible and width == 2:
                sum_sq = 0.0
                count = 0
                while True:
                    raw = wav.readframes(16384)
                    if not raw:
                        break
                    samples = len(raw) // 2
                    if samples <= 0:
                        continue
                    values = struct.unpack("<" + "h" * samples, raw[: samples * 2])
                    sum_sq += sum(float(value) * float(value) for value in values)
                    count += samples
                rms = math.sqrt(sum_sq / count) / 32768.0 if count else 0.0
                if rms < 1e-5:
                    raise AudioValidationError(f"{path.name} indeholder ingen målbar lyd.")

            return {
                "path": str(path),
                "duration": round(duration, 3),
                "sample_rate": rate,
                "channels": channels,
                "sample_width_bytes": width,
                "rms": round(rms, 6) if rms is not None else None,
            }
    except (wave.Error, EOFError, OSError) as exc:
        raise AudioValidationError(f"{path.name} er ikke en gyldig WAV-fil: {exc}") from exc
