from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from voicerig.app.netguard import allow_lan, is_loopback_client
from voicerig.app.pipeline import SUPPORTED_EXTENSIONS, SpeakerSelectionRequired, create_voice
from voicerig.app.tts_api import router as tts_router
from voicerig.config import data_dir, max_upload_mb, modelrig_base_url, modelrig_token
from voicerig.engines.package_runtime import status as tts_runtime_status
from voicerig.modelrig.client import ModelRigUnavailable, install_voice
from voicerig.profiles.package import validate_package
from voicerig.runtime import cuda_memory_stats, reset_cuda_peaks, voice_build_readiness
from voicerig.source_control import source_status

app = FastAPI(title="VoiceRig", version="0.1.0")
app.include_router(tts_router)
UI_FILE = Path(__file__).resolve().parents[1] / "ui" / "index.html"
_BUILD_LOCK = threading.Lock()


@app.middleware("http")
async def _loopback_only(request: Request, call_next):
    """Keep the unauthenticated voice/build surface local even if mis-bound.

    `run()` already binds 127.0.0.1. This request-level guard is the second
    boundary: starting the ASGI app manually with `--host 0.0.0.0` must not
    silently expose voice profiles, cloning or synthesis to the LAN.
    """
    if not allow_lan():
        peer = request.client.host if request.client else None
        if not is_loopback_client(peer):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "VoiceRig er loopback-only. Sæt VOICERIG_ALLOW_LAN=1 kun hvis "
                        "du bevidst vil eksponere servicen uden for denne maskine."
                    )
                },
            )
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return UI_FILE.read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> dict:
    readiness = voice_build_readiness()
    return {
        "ok": True,
        "service": "voicerig",
        "version": "0.1.0",
        "pid": os.getpid(),
        "source": source_status(),
        "hardware": readiness["hardware"],
        "voice_build_ready": readiness["ready"],
        "tts": tts_runtime_status(),
    }


@app.get("/api/readiness")
def readiness() -> dict:
    result = voice_build_readiness()
    result["source"] = source_status()
    result["pid"] = os.getpid()
    return result


@app.post("/api/voices")
def build_voice(
    name: str = Form(...),
    language: str = Form("da"),
    install_in_modelrig: bool = Form(True),
    speaker_choice: int | None = Form(None),
    speaker_anchor: str | None = Form(None),
    files: list[UploadFile] = File(...),
) -> dict:
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maksimalt 10 filer pr. stemme.")
    if speaker_choice is not None and speaker_anchor is not None:
        raise HTTPException(status_code=400, detail="Angiv kun ét stemmevalg.")
    if speaker_choice is not None and not 1 <= speaker_choice <= 4:
        raise HTTPException(status_code=400, detail="Ugyldigt stemmevalg.")
    if speaker_anchor is not None and (len(speaker_anchor) > 64 or ":" not in speaker_anchor):
        raise HTTPException(status_code=400, detail="Ugyldigt stemmeanker.")
    limit = max_upload_mb() * 1024 * 1024
    out_dir = data_dir() / "voices"
    if not _BUILD_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="VoiceRig arbejder allerede på en stemme. Prøv igen bagefter.")

    reset_cuda_peaks()
    try:
        with tempfile.TemporaryDirectory(prefix="voicerig-upload-") as tmp:
            sources: list[Path] = []
            total_size = 0
            for idx, upload in enumerate(files):
                suffix = Path(upload.filename or "").suffix.lower()
                if suffix not in SUPPORTED_EXTENSIONS:
                    raise HTTPException(status_code=415, detail=f"Filtypen {suffix or '?'} understøttes ikke.")
                target = Path(tmp) / f"input_{idx:02d}{suffix}"
                with target.open("wb") as f:
                    while chunk := upload.file.read(1024 * 1024):
                        total_size += len(chunk)
                        if total_size > limit:
                            raise HTTPException(
                                status_code=413,
                                detail=f"De samlede uploads overstiger grænsen på {max_upload_mb()} MB.",
                            )
                        f.write(chunk)
                sources.append(target)

            try:
                result = create_voice(
                    name,
                    sources,
                    out_dir,
                    language=language,
                    speaker_choice=speaker_choice,
                    speaker_anchor=speaker_anchor,
                )
            except SpeakerSelectionRequired as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "speaker_selection_required",
                        "message": str(exc),
                        "speakers": exc.choices,
                    },
                ) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        _BUILD_LOCK.release()

    installed = False
    install_detail = None
    base_url = modelrig_base_url()
    if install_in_modelrig and base_url:
        try:
            install_voice(base_url, result.package, token=modelrig_token())
            installed = True
        except ModelRigUnavailable as exc:
            install_detail = str(exc)

    manifest = validate_package(result.package)
    return {
        "ok": True,
        "voice": {
            "id": manifest["id"],
            "name": manifest["name"],
            "language": manifest["language"],
        },
        "package": result.package.name,
        "download_url": f"/api/packages/{result.package.name}",
        "installed_in_modelrig": installed,
        "modelrig_detail": install_detail,
        "diarization_used": result.diarization_used,
        "gpu": cuda_memory_stats(),
        "source": source_status(),
        "pid": os.getpid(),
    }


@app.get("/api/packages/{filename}")
def download_package(filename: str):
    safe = Path(filename).name
    if safe != filename or not safe.endswith(".mrvoice"):
        raise HTTPException(status_code=400, detail="Ugyldigt filnavn.")
    path = data_dir() / "voices" / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stemmeprofilen findes ikke.")
    return FileResponse(path, media_type="application/octet-stream", filename=safe)


def run() -> None:
    import uvicorn

    uvicorn.run("voicerig.app.main:app", host="127.0.0.1", port=8765, reload=False)
