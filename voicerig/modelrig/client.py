from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx


class ModelRigUnavailable(RuntimeError):
    pass


def _local_voices_dir() -> Path:
    value = os.getenv("MODELRIG_VOICES_DIR", "~/.kaliv/voices")
    return Path(value).expanduser().resolve()


def _is_loopback(base_url: str) -> bool:
    host = (urlparse(base_url).hostname or "").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


def _auth_headers(token: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"} if token else {}


def install_local(package: Path) -> dict:
    voices = _local_voices_dir()
    voices.mkdir(parents=True, exist_ok=True)
    destination = voices / package.name
    with tempfile.NamedTemporaryFile(dir=voices, delete=False, suffix=".tmp") as tmp:
        temp_path = Path(tmp.name)
    try:
        shutil.copy2(package, temp_path)
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)

    marker_tmp = voices / "default.txt.tmp"
    marker_tmp.write_text(destination.name + "\n", encoding="utf-8")
    os.replace(marker_tmp, voices / "default.txt")
    return {"ok": True, "installed": str(destination), "default": destination.name, "mode": "local"}


def install_voice(base_url: str, package: Path, timeout_s: float = 15.0, token: str | None = None) -> dict:
    if _is_loopback(base_url) and os.getenv("MODELRIG_LOCAL_INSTALL", "1") != "0":
        try:
            return install_local(package)
        except OSError as exc:
            raise ModelRigUnavailable("Kunne ikke installere stemmen i ModelRigs lokale voice-mappe.") from exc

    url = base_url.rstrip("/") + "/api/v1/voices/import"
    try:
        with package.open("rb") as f:
            response = httpx.post(
                url,
                files={"voice": (package.name, f, "application/octet-stream")},
                headers=_auth_headers(token),
                timeout=timeout_s,
            )
        if response.status_code >= 400:
            raise ModelRigUnavailable(f"ModelRig afviste stemmen: HTTP {response.status_code}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("ModelRig returnerede et ugyldigt importsvar.")
        return payload
    except ModelRigUnavailable:
        raise
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise ModelRigUnavailable("ModelRig kunne ikke kontaktes; stemmen er stadig gemt lokalt.") from exc


def status(base_url: str | None, token: str | None = None, timeout_s: float = 5.0) -> dict:
    """Read ModelRig's authenticated backend health without leaking credentials.

    VoiceRig deliberately treats backend reachability and TTS-provider state as
    separate signals. ModelRig may be online while TTS is degraded, and the UI
    needs to explain that distinction instead of flattening it into one bool.
    """
    if not base_url:
        return {
            "ok": False,
            "reachable": False,
            "configured": False,
            "base_url": None,
            "http_status": None,
            "tts": None,
            "detail": "ModelRig URL er ikke konfigureret.",
        }
    url = base_url.rstrip("/") + "/api/v1/health/full"
    try:
        response = httpx.get(url, headers=_auth_headers(token), timeout=timeout_s)
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "reachable": False,
            "configured": True,
            "base_url": base_url,
            "http_status": None,
            "tts": None,
            "detail": f"ModelRig kunne ikke kontaktes: {exc}",
        }

    if response.status_code >= 400:
        detail = "ModelRig afviste health-kaldet."
        if response.status_code in {401, 403}:
            detail = "ModelRig kræver et gyldigt MODELRIG_TOKEN."
        return {
            "ok": False,
            "reachable": True,
            "configured": True,
            "base_url": base_url,
            "http_status": response.status_code,
            "tts": None,
            "detail": detail,
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "ok": False,
            "reachable": True,
            "configured": True,
            "base_url": base_url,
            "http_status": response.status_code,
            "tts": None,
            "detail": "ModelRig returnerede ugyldig JSON fra health/full.",
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "reachable": True,
            "configured": True,
            "base_url": base_url,
            "http_status": response.status_code,
            "tts": None,
            "detail": "ModelRig health/full havde et ugyldigt format.",
        }

    checks = payload.get("checks") or {}
    tts = checks.get("tts") if isinstance(checks, dict) else None
    if not isinstance(tts, dict):
        tts = None
    backend_ok = payload.get("ok")
    if not isinstance(backend_ok, bool):
        backend_ok = True
    tts_ok = bool(tts and tts.get("ok")) if tts is not None else False
    return {
        "ok": bool(backend_ok and tts_ok),
        "reachable": True,
        "configured": True,
        "base_url": base_url,
        "http_status": response.status_code,
        "tts": {
            "ok": bool(tts.get("ok")),
            "provider": tts.get("provider"),
            "voice": tts.get("voice"),
            "package": tts.get("package"),
            "device": tts.get("device"),
            "detail": tts.get("detail"),
        } if tts is not None else None,
        "detail": None if tts_ok else "ModelRig er online, men TTS er ikke klar.",
    }
