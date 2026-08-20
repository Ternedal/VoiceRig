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


def source_status() -> dict:
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
