#!/usr/bin/env python3
"""CPU-only pyannote worker used from VoiceRig's separate diarization venv.

Why a subprocess? Chatterbox 0.1.7 pins torch/torchaudio 2.6.0 while current
pyannote.audio requires torch >=2.8. Keeping them in separate venvs avoids an
unsatisfiable dependency graph and also keeps diarization off the 12 GB GPU.

The protocol is intentionally tiny: input paths are argv, one JSON payload is
printed with a stable marker, diagnostics go to stderr.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_MARKER = "VOICERIG_DIARIZATION_JSON="


def _one(pipeline, path: str) -> dict:
    output = pipeline(path)
    timeline = getattr(output, "exclusive_speaker_diarization", None)
    if timeline is None:
        timeline = output.speaker_diarization

    segments = [
        {"start": float(turn.start), "end": float(turn.end), "speaker": str(speaker)}
        for turn, speaker in timeline
    ]
    totals: dict[str, float] = {}
    for seg in segments:
        totals[seg["speaker"]] = totals.get(seg["speaker"], 0.0) + max(
            0.0, seg["end"] - seg["start"]
        )

    labels = list(output.speaker_diarization.labels())
    raw_embeddings = getattr(output, "speaker_embeddings", None)
    speakers = []
    for idx, label in enumerate(labels):
        embedding = None
        if raw_embeddings is not None and idx < len(raw_embeddings):
            embedding = [float(v) for v in raw_embeddings[idx]]
        speakers.append(
            {
                "label": str(label),
                "duration": totals.get(str(label), 0.0),
                "embedding": embedding,
            }
        )
    return {"source": str(Path(path).resolve()), "segments": segments, "speakers": speakers}


def main() -> int:
    if len(sys.argv) < 2:
        print("pyannote worker requires at least one WAV path", file=sys.stderr)
        return 2
    try:
        from pyannote.audio import Pipeline
    except Exception as exc:
        print(f"pyannote.audio unavailable: {exc}", file=sys.stderr)
        return 2

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=token,
        )
        # Deliberately do not call .to(cuda): this worker owns the CPU-only
        # diarization environment and leaves GPU VRAM to Chatterbox/ModelRig.
        payload = [_one(pipeline, path) for path in sys.argv[1:]]
    except Exception as exc:
        print(f"speaker analysis failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    print(_MARKER + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
