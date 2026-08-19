from __future__ import annotations

from pathlib import Path

import httpx


class ModelRigUnavailable(RuntimeError):
    pass


def install_voice(base_url: str, package: Path, timeout_s: float = 15.0, token: str | None = None) -> dict:
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
