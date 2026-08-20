from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import Response

from voicerig import __version__
from voicerig.app.jobs import job_manager
from voicerig.app.pipeline import build_gate_status
from voicerig.config import modelrig_base_url, modelrig_token
from voicerig.diagnostics import build_support_bundle, configure_logging
from voicerig.modelrig.client import status as modelrig_status
from voicerig.profiles.library import list_voices
from voicerig.runtime import voice_build_readiness
from voicerig.source_control import source_status

router = APIRouter(tags=["operations"])


@router.on_event("startup")
def _configure_file_diagnostics() -> None:
    configure_logging()


def _safe_job(job: dict) -> dict:
    result = job.get("result") if isinstance(job.get("result"), dict) else None
    safe_result = None
    if result is not None:
        voice = result.get("voice") if isinstance(result.get("voice"), dict) else {}
        gpu = result.get("gpu") if isinstance(result.get("gpu"), dict) else None
        safe_result = {
            "voice": {
                "id": voice.get("id"),
                "name": voice.get("name"),
                "language": voice.get("language"),
            },
            "package": result.get("package"),
            "installed_in_modelrig": result.get("installed_in_modelrig"),
            "modelrig_detail": result.get("modelrig_detail"),
            "diarization_used": result.get("diarization_used"),
            "gpu": gpu,
        }
    return {
        "id": job.get("id"),
        "state": job.get("state"),
        "progress": job.get("progress"),
        "stage": job.get("stage"),
        "message": job.get("message"),
        "name": job.get("name"),
        "language": job.get("language"),
        "created_at": job.get("created_at"),
        "updated_at": job.get("updated_at"),
        "error": job.get("error"),
        "result": safe_result,
    }


def diagnostics_snapshot() -> dict:
    library = list_voices()
    voices = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "language": item.get("language"),
            "package": item.get("package"),
            "is_default": item.get("is_default"),
            "installed_in_modelrig": item.get("installed_in_modelrig"),
            "engine": item.get("engine"),
        }
        for item in library.get("voices") or []
    ]
    return {
        "service": "voicerig",
        "version": __version__,
        "source": source_status(),
        "readiness": voice_build_readiness(),
        "build": build_gate_status(),
        "modelrig": modelrig_status(modelrig_base_url(), token=modelrig_token()),
        "library": {
            "voice_count": len(voices),
            "invalid_count": len(library.get("invalid") or []),
            "default_package": library.get("default_package"),
            "voices": voices,
        },
        "jobs": [_safe_job(job) for job in job_manager.recent(limit=10)],
        "privacy": {
            "contains_source_audio": False,
            "contains_generated_wav": False,
            "contains_mrvoice": False,
            "contains_tokens": False,
            "contains_original_input_filenames": False,
        },
    }


@router.get("/api/diagnostics")
def diagnostics() -> dict:
    return {"ok": True, **diagnostics_snapshot()}


@router.get("/api/diagnostics/bundle")
def support_bundle():
    raw = build_support_bundle(diagnostics_snapshot())
    return Response(
        content=raw,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="voicerig-support.zip"'},
    )
