from __future__ import annotations

import subprocess
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _git(*args: str) -> str | None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo_root(),
            capture_output=True,
            text=True,
            check=False,
            timeout=5.0,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def current_source_status() -> dict:
    """Read the checkout identity as it exists right now."""

    revision = _git("rev-parse", "HEAD")
    branch = _git("branch", "--show-current")
    porcelain = _git("status", "--porcelain")
    return {
        "revision": revision,
        "branch": branch or None,
        "dirty": None if porcelain is None else bool(porcelain),
        "available": revision is not None,
        "root": str(repo_root().resolve()),
    }


# Service identity must describe the code/check-out state this Python process
# actually started from. Reading Git on every /api/health request lets a stale
# process appear to have moved to a newly checked-out revision even though its
# imported Python code has not changed. Freeze the source identity at import.
_PROCESS_SOURCE_STATUS = current_source_status()


def source_status() -> dict:
    """Return a defensive copy of this process' startup source identity."""

    return dict(_PROCESS_SOURCE_STATUS)
