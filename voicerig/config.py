from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    root = Path(os.getenv("VOICERIG_DATA_DIR", "voicerig-data")).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def modelrig_base_url() -> str | None:
    value = os.getenv("MODELRIG_BASE_URL", "http://127.0.0.1:8080").strip()
    return value or None


def max_upload_mb() -> int:
    try:
        value = int(os.getenv("VOICERIG_MAX_UPLOAD_MB", "2048"))
    except ValueError:
        value = 2048
    return max(1, value)


def modelrig_token() -> str | None:
    value = os.getenv("MODELRIG_TOKEN", "").strip()
    return value or None
