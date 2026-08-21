from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv, set_key

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LEGACY_DATA_DIR_ENV_VALUES = {"voicerig-data", "./voicerig-data"}
_LOCAL_SECRET_KEYS = {"MODELRIG_TOKEN"}


def _normalize_optional_hf_token() -> None:
    """Treat an empty HF_TOKEN as absent instead of an invalid bearer token.

    ``python-dotenv`` intentionally loads ``HF_TOKEN=`` as the empty string.
    Hugging Face clients normally interpret a missing token as anonymous access,
    but some downstream callers pass the raw environment value explicitly and
    therefore turn the empty string into the invalid HTTP header ``Bearer ``.
    Normalize only empty/whitespace values; a real session or .env token remains
    untouched.
    """
    token = os.getenv("HF_TOKEN")
    if token is not None and not token.strip():
        os.environ.pop("HF_TOKEN", None)


def load_local_env(path: Path | None = None) -> bool:
    """Load VoiceRig's repo-local .env without overriding real environment vars.

    The Windows launchers start VoiceRig directly, so relying on a shell to
    pre-export HF_TOKEN and the other documented settings makes first-run
    behaviour inconsistent. Loading `.env` here also means the separate
    pyannote subprocess inherits the same token/configuration automatically.
    """
    dotenv_path = (path or (_REPO_ROOT / ".env")).expanduser().resolve()
    loaded = False
    if dotenv_path.is_file():
        loaded = bool(load_dotenv(dotenv_path=dotenv_path, override=False))
    _normalize_optional_hf_token()
    return loaded


load_local_env()


def set_local_secret(key: str, value: str) -> bool:
    """Persist one explicitly allowed local secret without exposing it via APIs.

    The product UI needs to configure ModelRig authentication without asking the
    user to edit `.env` by hand. Keep this helper deliberately allow-listed so a
    future route cannot become an arbitrary environment-file writer.
    """
    if key not in _LOCAL_SECRET_KEYS:
        raise ValueError("Ugyldig lokal secret-nøgle.")
    if "\n" in value or "\r" in value:
        raise ValueError("Secret-værdien må ikke indeholde linjeskift.")
    if len(value) > 4096:
        raise ValueError("Secret-værdien er for lang.")

    env_path = (_REPO_ROOT / ".env").resolve()
    if not env_path.exists():
        example = _REPO_ROOT / ".env.example"
        if example.is_file():
            shutil.copy2(example, env_path)
        else:
            env_path.touch()

    clean = value.strip()
    set_key(str(env_path), key, clean, quote_mode="always")
    if clean:
        os.environ[key] = clean
        return True
    os.environ.pop(key, None)
    return False


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
