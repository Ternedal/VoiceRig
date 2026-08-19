#!/usr/bin/env python3
"""CPU-only pyannote worker used from VoiceRig's separate diarization venv.

Why a subprocess? Chatterbox and current pyannote have incompatible torch
requirements. Keeping them in separate venvs avoids an unsatisfiable dependency
graph and also keeps diarization off the 12 GB GPU.

The protocol is intentionally tiny: input paths are argv, one JSON payload is
printed with a stable marker, diagnostics go to stderr. `--preload` downloads
and verifies the community-1 pipeline without processing user audio.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_MARKER = "VOICERIG_DIARIZATION_JSON="
_READY_MARKER = "VOICERIG_DIARIZATION_READY="
_MODEL_ID = "pyannote/speaker-diarization-community-1"

# VoiceRig is local-first. pyannote telemetry does not contain audio, but it can
# include model origin, file duration and speaker-count parameters. Disable it
# unless the user explicitly opts in with PYANNOTE_METRICS_ENABLED=1.
os.environ.setdefault("PYANNOTE_METRICS_ENABLED", "0")


def _load_pipeline():
    try:
        from pyannote.audio import Pipeline
    except Exception as exc:
        raise RuntimeError(f"pyannote.audio unavailable: {exc}") from exc

    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN")
    return Pipeline.from_pretrained(_MODEL_ID, token=token)


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
    args = sys.argv[1:]
    if not args:
        print("pyannote worker requires WAV paths or --preload", file=sys.stderr)
        return 2

    try:
        pipeline = _load_pipeline()
    except Exception as exc:
        print(f"speaker model load failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    if args == ["--preload"]:
        try:
            import pyannote.audio
            package_version = str(pyannote.audio.__version__)
        except Exception as exc:
            print(f"pyannote version unavailable: {exc}", file=sys.stderr)
            return 3
        print(
            _READY_MARKER
            + json.dumps(
                {
                    "ok": True,
                    "model": _MODEL_ID,
                    "package_version": package_version,
                    "telemetry": os.getenv("PYANNOTE_METRICS_ENABLED", "0"),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 0

    if any(arg.startswith("--") for arg in args):
        print("unknown pyannote worker option", file=sys.stderr)
        return 2

    try:
        # Deliberately do not call .to(cuda): this worker owns the CPU-only
        # diarization environment and leaves GPU VRAM to Chatterbox/ModelRig.
        payload = [_one(pipeline, path) for path in args]
    except Exception as exc:
        print(f"speaker analysis failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    print(_MARKER + json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
