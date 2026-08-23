from __future__ import annotations

"""Standalone OmniVoice inference worker.

This file is intentionally executable without importing the VoiceRig package.
The parent VoiceRig process launches it with the isolated OmniVoice virtualenv
so OmniVoice's Torch/Transformers dependency surface never mutates Chatterbox.
"""

import argparse
import json
from pathlib import Path

_RESULT_MARKER = "VOICERIG_OMNIVOICE_RESULT="


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    request_path = Path(args.request).resolve()
    output = Path(args.output).resolve()
    payload = json.loads(request_path.read_text(encoding="utf-8"))

    reference = Path(str(payload["reference"])).resolve()
    text = str(payload["text"]).strip()
    if not reference.is_file():
        raise RuntimeError("OmniVoice-referencefilen mangler.")
    if not text:
        raise RuntimeError("OmniVoice-testteksten er tom.")

    import soundfile as sf
    import torch
    from huggingface_hub import snapshot_download
    from omnivoice import OmniVoice

    if not torch.cuda.is_available():
        raise RuntimeError("OmniVoice-runtime fandt ingen CUDA-GPU.")

    # Resolve immutable model snapshots ourselves. OmniVoice's helper resolves a
    # repository id without forwarding Hugging Face `revision`, so a local path
    # is the only deterministic way to bind the physical comparison to exact
    # weights.
    model_dir = snapshot_download(
        repo_id=str(payload["model_repo"]),
        revision=str(payload["model_revision"]),
    )
    asr_dir = snapshot_download(
        repo_id=str(payload["asr_repo"]),
        revision=str(payload["asr_revision"]),
    )

    # Reference transcripts are not stored in .mrvoice v1. Let OmniVoice's
    # documented Whisper path transcribe the short reference, but keep Whisper
    # on CPU so the 12 GB target GPU is reserved for voice generation.
    model = OmniVoice.from_pretrained(
        model_dir,
        device_map="cuda:0",
        dtype=torch.float16,
        asr_model_name=asr_dir,
        asr_device="cpu",
        load_asr=True,
    )
    audio = model.generate(
        text=text,
        language="da",
        ref_audio=str(reference),
        normalize_text=False,
    )
    if not audio:
        raise RuntimeError("OmniVoice returnerede ingen lyd.")

    sample_rate = int(model.sampling_rate or 24000)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(output), audio[0], sample_rate, subtype="PCM_16")
    frames = int(len(audio[0]))
    result = {
        "engine": "OmniVoice",
        "model": str(payload["model_repo"]),
        "model_revision": str(payload["model_revision"]),
        "source_revision": str(payload["source_revision"]),
        "sample_rate": sample_rate,
        "duration": round(frames / sample_rate, 3) if sample_rate else 0.0,
        "language": "da",
    }
    print(_RESULT_MARKER + json.dumps(result, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
