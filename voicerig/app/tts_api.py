from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from voicerig.engines.package_runtime import resolve_package, status, synthesize
from voicerig.engines.rost import synthesize_rost_danish
from voicerig.profiles.package import validate_package
from voicerig.runtime import cuda_memory_stats

router = APIRouter()


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice_package: str | None = None


@router.get("/api/tts/status")
def tts_status() -> dict:
    return status()


@router.post("/api/tts/synthesize")
def tts_synthesize(req: SynthesizeRequest):
    try:
        package = resolve_package(req.voice_package)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        with tempfile.TemporaryDirectory(prefix="voicerig-tts-") as tmp:
            output = Path(tmp) / "speech.wav"
            meta = synthesize(package, req.text, output)
            raw = output.read_bytes()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    gpu = cuda_memory_stats()
    headers = {
        "X-VoiceRig-Voice": str(meta["voice"]),
        "X-VoiceRig-Voice-ID": str(meta["voice_id"]),
        "X-VoiceRig-Package": str(meta["package"]),
        "X-VoiceRig-Sample-Rate": str(meta["sample_rate"]),
        "X-VoiceRig-Duration": str(meta["duration"]),
        "X-VoiceRig-Device": str(meta["device"]),
    }
    # The build endpoint resets PyTorch peak counters. These headers therefore
    # provide the same long-lived process' peak after the subsequent TTS call,
    # which is the physically meaningful number for a 12 GB acceptance run.
    if gpu.get("available"):
        headers["X-VoiceRig-Peak-Allocated-GB"] = str(gpu["peak_allocated_gb"])
        headers["X-VoiceRig-Peak-Reserved-GB"] = str(gpu["peak_reserved_gb"])
        headers["X-VoiceRig-Allocated-GB"] = str(gpu["allocated_gb"])
        headers["X-VoiceRig-Reserved-GB"] = str(gpu["reserved_gb"])

    return Response(content=raw, media_type="audio/wav", headers=headers)


@router.post("/api/tts/compare/rost")
def tts_compare_rost(req: SynthesizeRequest):
    """Generate a Danish Røst sample without changing the installed voice.

    The source .mrvoice stays untouched. We only extract its validated
    reference.wav into a private temporary directory and run the pinned Danish
    checkpoint against the same user-supplied test text.
    """
    try:
        package = resolve_package(req.voice_package)
        manifest = validate_package(package)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    language = str(manifest.get("language") or "").lower().split("-", 1)[0]
    if language != "da":
        raise HTTPException(status_code=422, detail="Røst-sammenligningen er kun til danske profiler.")

    try:
        with tempfile.TemporaryDirectory(prefix="voicerig-rost-compare-") as tmp:
            root = Path(tmp)
            reference = root / "reference.wav"
            with zipfile.ZipFile(package, "r") as zf:
                reference.write_bytes(zf.read("reference.wav"))
            output = root / "rost.wav"
            meta = synthesize_rost_danish(reference, req.text, output)
            raw = output.read_bytes()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # HTTP header values must stay byte/ASCII-safe across ASGI servers and test
    # clients. Keep the human-facing Røst spelling in the UI/body; use an ASCII
    # transliteration only in transport metadata.
    headers = {
        "X-VoiceRig-Engine": "Roest v3 Chatterbox 500M",
        "X-VoiceRig-Model": str(meta["model"]),
        "X-VoiceRig-Revision": str(meta["revision"]),
        "X-VoiceRig-Sample-Rate": str(meta["sample_rate"]),
        "X-VoiceRig-Duration": str(meta["duration"]),
        "X-VoiceRig-Language": str(meta["language"]),
    }
    return Response(content=raw, media_type="audio/wav", headers=headers)
