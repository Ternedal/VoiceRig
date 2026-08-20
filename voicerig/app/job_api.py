from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from voicerig.app.job_retention import prune_job_history
from voicerig.app.jobs import job_manager
from voicerig.app.pipeline import SUPPORTED_EXTENSIONS
from voicerig.config import max_upload_mb

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.on_event("startup")
def _recover_interrupted_jobs() -> None:
    job_manager.recover()
    prune_job_history()


@router.get("")
def recent_jobs(limit: int = 20) -> dict:
    prune_job_history()
    return {"ok": True, "jobs": job_manager.recent(limit=limit)}


@router.post("/voices", status_code=status.HTTP_202_ACCEPTED)
def start_voice_job(
    name: str = Form(...),
    language: str = Form("da"),
    install_in_modelrig: bool = Form(True),
    files: list[UploadFile] = File(...),
) -> dict:
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="Maksimalt 10 filer pr. stemme.")
    if not name.strip():
        raise HTTPException(status_code=422, detail="Stemmen skal have et navn.")

    prune_job_history()
    limit = max_upload_mb() * 1024 * 1024
    with tempfile.TemporaryDirectory(prefix="voicerig-job-upload-") as tmp:
        staged: list[tuple[str, Path]] = []
        total_size = 0
        for idx, upload in enumerate(files):
            original_name = Path(upload.filename or "").name
            suffix = Path(original_name).suffix.lower()
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
            staged.append((original_name or f"klip-{idx + 1}{suffix}", target))
        try:
            job = job_manager.create(name, language, install_in_modelrig, staged)
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True, "job": job}


@router.get("/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        return {"ok": True, "job": job_manager.get(job_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{job_id}/speaker")
def choose_job_speaker(job_id: str, anchor: str = Form(...)) -> dict:
    if len(anchor) > 64 or ":" not in anchor:
        raise HTTPException(status_code=400, detail="Ugyldigt speaker-anker.")
    try:
        return {"ok": True, "job": job_manager.choose_speaker(job_id, anchor)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    try:
        return {"ok": True, "job": job_manager.cancel(job_id)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
