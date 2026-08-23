from __future__ import annotations

"""Standalone OmniVoice inference worker.

This module is intentionally executable inside the isolated OmniVoice virtualenv
without importing VoiceRig's runtime dependency graph. The parent launches it as
``python -m voicerig.engines.omnivoice_worker`` from the package root so the
third-party ``omnivoice`` distribution cannot be shadowed by VoiceRig's sibling
``voicerig.engines.omnivoice`` module.
"""

import argparse
import importlib.metadata as metadata
import importlib.util
import json
from pathlib import Path
import sys

_RESULT_MARKER = "VOICERIG_OMNIVOICE_RESULT="


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def _installed_source_revision(expected: str) -> str:
    """Prove the worker itself imports the pinned pip VCS checkout."""
    try:
        dist = metadata.distribution("omnivoice")
        direct = json.loads(dist.read_text("direct_url.json") or "{}")
    except Exception as exc:
        raise RuntimeError("OmniVoice-worker kunne ikke læse installeret source-identitet.") from exc

    vcs = direct.get("vcs_info") if isinstance(direct, dict) else None
    vcs = vcs if isinstance(vcs, dict) else {}
    actual = str(vcs.get("commit_id") or "").strip().lower()
    required = str(expected or "").strip().lower()
    if vcs.get("vcs") != "git" or len(required) != 40 or actual != required:
        raise RuntimeError(
            "OmniVoice-worker source-identitet matcher ikke VoiceRigs pinnede revision."
        )
    return actual


def _external_import_origin() -> str:
    """Require top-level ``omnivoice`` to resolve inside this isolated venv.

    PEP 610 proves which distribution pip installed, but it does not prove what
    Python will import when another module with the same top-level name shadows
    it on ``sys.path``. RC21 hit exactly that failure mode when this worker was
    executed as a file from ``voicerig/engines``. Bind the import target to the
    isolated interpreter prefix before importing the heavyweight model package.
    """
    spec = importlib.util.find_spec("omnivoice")
    origin_value = getattr(spec, "origin", None) if spec is not None else None
    if not origin_value:
        raise RuntimeError("OmniVoice-worker kunne ikke resolve den installerede omnivoice-pakke.")

    origin = Path(str(origin_value)).resolve()
    runtime_prefix = Path(sys.prefix).resolve()
    try:
        origin.relative_to(runtime_prefix)
    except ValueError as exc:
        raise RuntimeError(
            f"OmniVoice-import blev shadowed uden for den isolerede runtime: {origin}"
        ) from exc
    return str(origin)


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

    # Re-check both distribution identity and Python's actual import target in
    # the inference process. These are deliberately separate properties.
    source_revision = _installed_source_revision(str(payload["source_revision"]))
    import_origin = _external_import_origin()

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
        "source_revision": source_revision,
        "import_origin": import_origin,
        "sample_rate": sample_rate,
        "duration": round(frames / sample_rate, 3) if sample_rate else 0.0,
        "language": "da",
    }
    print(_RESULT_MARKER + json.dumps(result, ensure_ascii=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
