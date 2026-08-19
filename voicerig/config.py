from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]


def load_local_env(path: Path | None = None) -> bool:
    """Load VoiceRig's repo-local .env without overriding real environment vars.

    The Windows launchers start VoiceRig directly, so relying on a shell to
    pre-export HF_TOKEN and the other documented settings makes first-run
    behaviour inconsistent. Loading `.env` here also means the separate
    pyannote subprocess inherits the same token/configuration automatically.
    """
    dotenv_path = (path or (_REPO_ROOT / ".env")).expanduser().resolve()
    if not dotenv_path.is_file():
        return False
    return bool(load_dotenv(dotenv_path=dotenv_path, override=False))


# Deterministic product configuration: OS/session environment wins, `.env`
# fills only missing values.
load_local_env()


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


def allow_undiarized_fallback() -> bool:
    """Unsafe/developer escape hatch; product builds fail closed by default.

    Without diarization VoiceRig cannot know whether an interview/video contains
    one or several people, so silently cloning the raw audio is not safe enough
    for the normal 'drop clips and forget the details' workflow.
    """
    return os.getenv("VOICERIG_ALLOW_UNDIARIZED", "0").strip().lower() in {"1", "true", "yes", "on"}
