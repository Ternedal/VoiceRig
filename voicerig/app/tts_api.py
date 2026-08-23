from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from voicerig.engines.omnivoice import synthesize_omnivoice_danish
from voicerig.engines.package_runtime import resolve_package, status, synthesize
from voicerig.engines.rost import synthesize_rost_danish
from voicerig.profiles.package import validate_package
from voicerig.runtime import cuda_memory_stats

router = APIRouter()


def _ascii_header(value: object) -> str:
    """Return deterministic percent-UTF8 transport text safe for HTTP headers."""
    return quote(str(value), safe="._-")


class SynthesizeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice_package: str | None = None


class VoicePackageRequest(BaseModel):
    voice_package: str | None = None


class RostReferenceRequest(SynthesizeRequest):
    reference_index: int = Field(ge=0, le=5)


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
        "X-VoiceRig-Voice": _ascii_header(meta["voice"]),
        "X-VoiceRig-Voice-ID": _ascii_header(meta["voice_id"]),
        "X-VoiceRig-Package": _ascii_header(meta["package"]),
        "X-VoiceRig-Sample-Rate": str(meta["sample_rate"]),
        "X-VoiceRig-Duration": str(meta["duration"]),
        "X-VoiceRig-Device": _ascii_header(meta["device"]),
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


def _resolve_danish_package(voice_package: str | None, engine_label: str) -> tuple[Path, dict]:
    try:
        package = resolve_package(voice_package)
        manifest = validate_package(package)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    language = str(manifest.get("language") or "").lower().split("-", 1)[0]
    if language != "da":
        raise HTTPException(
            status_code=422,
            detail=f"{engine_label}-sammenligningen er kun til danske profiler.",
        )
    return package, manifest


def _reference_members(package: Path) -> list[str]:
    """Return the validated primary reference followed by stored alternatives."""
    with zipfile.ZipFile(package, "r") as zf:
        names = set(zf.namelist())
    members = ["reference.wav"]
    members.extend(
        name
        for name in (f"references/candidate_{idx:02d}.wav" for idx in range(1, 6))
        if name in names
    )
    return members


def _extract_reference(package: Path, root: Path, reference_index: int = 0) -> Path:
    members = _reference_members(package)
    if reference_index < 0 or reference_index >= len(members):
        raise ValueError("Den valgte Røst-reference findes ikke i stemmeprofilen.")
    member = members[reference_index]
    reference = root / f"reference-{reference_index:02d}.wav"
    with zipfile.ZipFile(package, "r") as zf:
        reference.write_bytes(zf.read(member))
    return reference


def _rost_response(package: Path, text: str, reference_index: int = 0) -> Response:
    try:
        with tempfile.TemporaryDirectory(prefix="voicerig-rost-compare-") as tmp:
            root = Path(tmp)
            reference = _extract_reference(package, root, reference_index)
            output = root / "rost.wav"
            meta = synthesize_rost_danish(reference, text, output)
            raw = output.read_bytes()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    headers = {
        "X-VoiceRig-Engine": "Roest v3 Chatterbox 500M",
        "X-VoiceRig-Model": _ascii_header(meta["model"]),
        "X-VoiceRig-Revision": _ascii_header(meta["revision"]),
        "X-VoiceRig-Sample-Rate": str(meta["sample_rate"]),
        "X-VoiceRig-Duration": str(meta["duration"]),
        "X-VoiceRig-Language": _ascii_header(meta["language"]),
        "X-VoiceRig-Reference-Index": str(reference_index),
    }
    return Response(content=raw, media_type="audio/wav", headers=headers)


@router.post("/api/tts/compare/rost")
def tts_compare_rost(req: SynthesizeRequest):
    """Generate a Danish Røst sample without changing the installed voice."""
    package, _manifest = _resolve_danish_package(req.voice_package, "Røst")
    return _rost_response(package, req.text, 0)


@router.post("/api/tts/compare/rost/references")
def tts_compare_rost_references(req: VoicePackageRequest) -> dict:
    """List package references available for non-mutating Røst identity auditions."""
    package, _manifest = _resolve_danish_package(req.voice_package, "Røst")
    members = _reference_members(package)
    return {
        "references": [
            {
                "index": index,
                "label": "Røst reference 1 (primær)" if index == 0 else f"Røst reference {index + 1}",
            }
            for index, _member in enumerate(members)
        ]
    }


@router.post("/api/tts/compare/rost/reference")
def tts_compare_rost_reference(req: RostReferenceRequest):
    """Generate Røst from one stored .mrvoice reference while holding all model controls fixed."""
    package, _manifest = _resolve_danish_package(req.voice_package, "Røst")
    return _rost_response(package, req.text, req.reference_index)


@router.post("/api/tts/compare/omnivoice")
def tts_compare_omnivoice(req: SynthesizeRequest):
    """Generate an isolated Danish OmniVoice sample from the same reference.

    The source .mrvoice and ModelRig default stay untouched. OmniVoice runs in a
    separately versioned local venv/process so its Torch/Transformers stack
    cannot change the verified Chatterbox runtime.
    """
    package, _manifest = _resolve_danish_package(req.voice_package, "OmniVoice")

    try:
        with tempfile.TemporaryDirectory(prefix="voicerig-omnivoice-compare-") as tmp:
            root = Path(tmp)
            reference = _extract_reference(package, root)
            output = root / "omnivoice.wav"
            meta = synthesize_omnivoice_danish(reference, req.text, output)
            raw = output.read_bytes()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    headers = {
        "X-VoiceRig-Engine": "OmniVoice",
        "X-VoiceRig-Model": _ascii_header(meta["model"]),
        "X-VoiceRig-Revision": _ascii_header(meta["model_revision"]),
        "X-VoiceRig-Source-Revision": _ascii_header(meta["source_revision"]),
        "X-VoiceRig-Sample-Rate": str(meta["sample_rate"]),
        "X-VoiceRig-Duration": str(meta["duration"]),
        "X-VoiceRig-Language": _ascii_header(meta["language"]),
    }
    return Response(content=raw, media_type="audio/wav", headers=headers)
