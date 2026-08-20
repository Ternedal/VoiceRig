from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LEGACY_DATA_DIR_ENV_VALUES = {"voicerig-data", "./voicerig-data"}


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


load_local_env()


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        local = os.getenv("LOCALAPPDATA", "").strip()
        if local:
            return Path(local).expanduser() / "VoiceRig"
        return Path.home() / "AppData" / "Local" / "VoiceRig"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "VoiceRig"
    xdg = os.getenv("XDG_DATA_HOME", "").strip()
    return (Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share") / "voicerig"


def _legacy_repo_data_dir() -> Path:
    return (_REPO_ROOT / "voicerig-data").resolve()


def _is_legacy_data_dir_setting(value: str) -> bool:
    """Recognize the old repo-relative default without swallowing custom paths.

    Early VoiceRig .env files shipped with ``VOICERIG_DATA_DIR=voicerig-data``.
    Treating that value as an explicit override defeats the newer stable
    per-user storage location, so upgrades must interpret only those exact
    historical relative spellings as the legacy default.
    """
    normalized = value.strip().replace("\\", "/").rstrip("/")
    return normalized in _LEGACY_DATA_DIR_ENV_VALUES


def data_dir() -> Path:
    explicit = os.getenv("VOICERIG_DATA_DIR", "").strip()
    if explicit and not _is_legacy_data_dir_setting(explicit):
        root = Path(explicit).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    target = _default_data_dir().expanduser().resolve()
    legacy = _legacy_repo_data_dir()
    if not target.exists() and legacy.is_dir() and legacy != target:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(legacy), str(target))
        except OSError:
            # Never hide existing jobs/profiles/readiness just because migration
            # could not complete. Continue from the old location and let the
            # diagnostics/UI surface the installation issue instead of losing data.
            legacy.mkdir(parents=True, exist_ok=True)
            return legacy

    target.mkdir(parents=True, exist_ok=True)
    return target


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
