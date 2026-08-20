from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from voicerig.config import data_dir

_TERMINAL = {"succeeded", "failed", "cancelled"}


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _atomic_json(path: Path, payload: dict) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".json.tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def prune_job_history(
    *,
    root: Path | None = None,
    now: datetime | None = None,
    paused_max_age_days: int = 7,
    terminal_max_age_days: int = 30,
    max_terminal_jobs: int = 100,
) -> dict:
    """Bound local job metadata and private paused-job inputs.

    Active queued/running/cancelling jobs are never touched. Jobs waiting for a
    speaker choice retain their local inputs only for a bounded period so a
    forgotten browser session cannot keep private source media indefinitely.
    """
    jobs_root = root or (data_dir() / "jobs")
    jobs_root.mkdir(parents=True, exist_ok=True)
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    paused_cutoff = current - timedelta(days=max(1, int(paused_max_age_days)))
    terminal_cutoff = current - timedelta(days=max(1, int(terminal_max_age_days)))
    max_terminal = max(1, int(max_terminal_jobs))

    terminal: list[tuple[datetime, Path, dict]] = []
    expired_paused = 0
    deleted_terminal = 0

    for path in jobs_root.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not payload.get("id"):
            continue
        job_id = str(payload["id"])
        state = payload.get("state")
        updated = _parse_time(payload.get("updated_at")) or _parse_time(payload.get("created_at"))
        if updated is None:
            continue

        if state == "needs_speaker" and updated < paused_cutoff:
            payload.update(
                state="cancelled",
                stage="cancelled",
                progress=int(payload.get("progress") or 40),
                message="Jobbet udløb efter 7 dage uden speaker-valg. Kildeklippene er slettet.",
                speaker_choices=None,
                speaker_anchor=None,
                error=None,
                updated_at=current.isoformat(),
            )
            try:
                _atomic_json(path, payload)
                shutil.rmtree(jobs_root / job_id, ignore_errors=True)
                expired_paused += 1
            except OSError:
                pass
            continue

        if state in _TERMINAL:
            shutil.rmtree(jobs_root / job_id, ignore_errors=True)
            terminal.append((updated, path, payload))

    terminal.sort(key=lambda item: item[0], reverse=True)
    for index, (updated, path, _payload) in enumerate(terminal):
        if updated < terminal_cutoff or index >= max_terminal:
            try:
                path.unlink(missing_ok=True)
                deleted_terminal += 1
            except OSError:
                pass

    return {
        "ok": True,
        "expired_paused": expired_paused,
        "deleted_terminal": deleted_terminal,
        "paused_max_age_days": max(1, int(paused_max_age_days)),
        "terminal_max_age_days": max(1, int(terminal_max_age_days)),
        "max_terminal_jobs": max_terminal,
    }
