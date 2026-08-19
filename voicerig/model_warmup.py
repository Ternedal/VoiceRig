from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from voicerig.analysis.diarization import _worker_python
from voicerig.config import load_local_env
from voicerig.engines.chatterbox import _shared_model

_READY_MARKER = "VOICERIG_DIARIZATION_READY="


def warm_chatterbox() -> dict:
    """Download/load the exact Chatterbox V3 runtime and verify Danish support."""
    model = _shared_model()
    try:
        supported = model.get_supported_languages()
    except Exception as exc:
        raise RuntimeError("Chatterbox kunne ikke rapportere understøttede sprog.") from exc
    if "da" not in supported:
        raise RuntimeError("Den installerede Chatterbox-kode understøtter ikke dansk V3.")
    return {
        "ok": True,
        "engine": "chatterbox-multilingual",
        "model": "v3",
        "language": "da",
        "device": str(getattr(model, "device", "unknown")),
        "sample_rate": int(getattr(model, "sr", 0) or 0),
    }


def warm_diarization(timeout_seconds: float = 1800.0) -> dict:
    """Download/load pyannote community-1 in the isolated CPU-only runtime."""
    python = _worker_python()
    worker = Path(__file__).resolve().parent / "analysis" / "pyannote_worker.py"
    env = os.environ.copy()
    env.setdefault("PYANNOTE_METRICS_ENABLED", "0")
    try:
        proc = subprocess.run(
            [str(python), str(worker), "--preload"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"pyannote-modelkontrollen kunne ikke startes: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "ukendt fejl").strip()[:1200]
        raise RuntimeError(
            "pyannote community-1 kunne ikke downloades/åbnes. Acceptér modellens "
            "Hugging Face-vilkår og sæt HF_TOKEN i .env (eller log ind med Hugging "
            f"Face CLI), og kør setup igen. Detalje: {detail}"
        )
    line = next(
        (item for item in reversed(proc.stdout.splitlines()) if item.startswith(_READY_MARKER)),
        None,
    )
    if line is None:
        raise RuntimeError("pyannote-worker bekræftede ikke model-warmup.")
    try:
        payload = json.loads(line[len(_READY_MARKER):])
    except (json.JSONDecodeError, TypeError) as exc:
        raise RuntimeError("pyannote-worker returnerede ugyldigt warmup-resultat.") from exc
    if not payload.get("ok"):
        raise RuntimeError("pyannote-worker rapporterede, at modellen ikke er klar.")
    return payload


def warm_models() -> dict:
    # setup-windows.ps1 runs this module directly. Reload the repo-local .env so
    # HF_TOKEN and privacy/configuration defaults are guaranteed to be present
    # before either model loader starts. Existing OS/session vars still win.
    load_local_env()
    chatterbox = warm_chatterbox()
    diarization = warm_diarization()
    return {"ok": True, "chatterbox": chatterbox, "diarization": diarization}


def main() -> int:
    try:
        report = warm_models()
    except Exception as exc:
        print(f"VoiceRig model-warmup: FAIL\n{type(exc).__name__}: {exc}")
        return 1
    print("VoiceRig model-warmup: PASS")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
