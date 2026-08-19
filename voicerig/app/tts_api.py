from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from voicerig.engines.package_runtime import resolve_package, status, synthesize

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

    return Response(
        content=raw,
        media_type="audio/wav",
        headers={
            "X-VoiceRig-Voice": str(meta["voice"]),
            "X-VoiceRig-Voice-ID": str(meta["voice_id"]),
            "X-VoiceRig-Package": str(meta["package"]),
            "X-VoiceRig-Sample-Rate": str(meta["sample_rate"]),
            "X-VoiceRig-Duration": str(meta["duration"]),
            "X-VoiceRig-Device": str(meta["device"]),
        },
    )
