from __future__ import annotations

import io
import json
import logging
import logging.handlers
import re
import threading
import zipfile
from pathlib import Path

from voicerig.config import data_dir

_LOG_LOCK = threading.Lock()
_CONFIGURED = False
_MAX_LOG_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 3
_SUPPORT_LOG_TAIL = 512 * 1024

_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:HF_TOKEN|MODELRIG_TOKEN)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"(?i)(token=)[^&\s]+"),
)


class _RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for pattern in _SECRET_PATTERNS:
            text = pattern.sub(r"\1[REDACTED]", text)
        return text


def log_dir() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_file() -> Path:
    return log_dir() / "voicerig.log"


def configure_logging() -> None:
    global _CONFIGURED
    with _LOG_LOCK:
        if _CONFIGURED:
            return
        handler = logging.handlers.RotatingFileHandler(
            log_file(),
            maxBytes=_MAX_LOG_BYTES,
            backupCount=_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(
            _RedactingFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        handler.setLevel(logging.INFO)
        logger = logging.getLogger("voicerig")
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        logger.propagate = True
        _CONFIGURED = True
        logger.info("VoiceRig file diagnostics initialized")


def _redact_text(text: str) -> str:
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1[REDACTED]", text)
    return text


def recent_log_text(max_bytes: int = _SUPPORT_LOG_TAIL) -> str:
    path = log_file()
    if not path.is_file():
        return ""
    limit = max(1024, min(int(max_bytes), _SUPPORT_LOG_TAIL))
    try:
        with path.open("rb") as fh:
            size = path.stat().st_size
            if size > limit:
                fh.seek(size - limit)
                fh.readline()
            raw = fh.read(limit)
        return _redact_text(raw.decode("utf-8", "replace"))
    except OSError as exc:
        return f"Kunne ikke læse VoiceRig-loggen: {exc}"


def build_support_bundle(snapshot: dict) -> bytes:
    """Build a metadata-only support ZIP.

    The caller supplies an already sanitized snapshot. This function only adds
    that JSON and the redacted text log; it never scans data directories, so it
    cannot accidentally include source clips, generated WAVs or `.mrvoice`
    profiles.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "diagnostics.json",
            json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True),
        )
        zf.writestr("voicerig.log", recent_log_text())
        zf.writestr(
            "README.txt",
            "VoiceRig support bundle. Indeholder kun diagnostikmetadata og redigeret log.\n"
            "Kildeaudio, WAV-filer, .mrvoice-profiler og tokens er ikke inkluderet.\n",
        )
    return buffer.getvalue()
