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
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            response = httpx.post(
                url,
                files={"voice": (package.name, f, "application/octet-stream")},
                headers=headers,
                timeout=timeout_s,
            )
        if response.status_code >= 400:
            raise ModelRigUnavailable(f"ModelRig afviste stemmen: HTTP {response.status_code}")
        return response.json()
    except (httpx.HTTPError, OSError, ValueError) as exc:
        raise ModelRigUnavailable("ModelRig kunne ikke kontaktes; stemmen er stadig gemt lokalt.") from exc
