from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from voicerig.app.pipeline import (
    SUPPORTED_EXTENSIONS,
    SpeakerSelectionRequired,
    create_voice,
)
from voicerig.app.tts_api import router as tts_router
from voicerig.config import data_dir, max_upload_mb, modelrig_base_url, modelrig_token
from voicerig.engines.package_runtime import status as tts_runtime_status
from voicerig.modelrig.client import ModelRigUnavailable, install_voice
from voicerig.profiles.package import validate_package
from voicerig.runtime import voice_build_readiness

app = FastAPI(title="VoiceRig", version="0.1.0")
app.include_router(tts_router)
UI_FILE = Path(__file__).resolve().parents[1] / "ui" / "index.html"
_BUILD_LOCK = threading.Lock()


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
        "hardware": readiness["hardware"],
        "voice_build_ready": readiness["ready"],
        "tts": tts_runtime_status(),
    }


@app.get("/api/readiness")
def readiness() -> dict:
    return voice_build_readiness()


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
    if speaker_choice is not None and not 1 <= speaker_choice <= 4:
        raise HTTPException(status_code=400, detail="Ugyldigt stemmevalg.")
    if speaker_anchor is not None and (len(speaker_anchor) > 64 or ":" not in speaker_anchor):
        raise HTTPException(status_code=400, detail="Ugyldigt stemmeanker.")
    limit = max_upload_mb() * 1024 * 1024
    out_dir = data_dir() / "voices"
    if not _BUILD_LOCK.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="VoiceRig arbejder allerede på en stemme. Prøv igen bagefter.")

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
        "voice": {"id": manifest["id"], "name": manifest["name"], "language": manifest["language"]},
        "package": result.package.name,
        "download_url": f"/api/packages/{result.package.name}",
        "installed_in_modelrig": installed,
        "modelrig_detail": install_detail,
        "diarization_used": result.diarization_used,
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
