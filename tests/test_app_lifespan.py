"""The two startup hooks run from the app lifespan (not the deprecated
@router.on_event), in the historical order: jobs recovery, then logging."""
from __future__ import annotations

import subprocess
import sys
from unittest import mock

from fastapi.testclient import TestClient

import voicerig.app.main as main


def test_startup_hooks_run_once_in_order_under_lifespan():
    calls: list[str] = []
    with mock.patch.object(main, "recover_interrupted_jobs", side_effect=lambda: calls.append("jobs")), \
         mock.patch.object(main, "configure_file_diagnostics", side_effect=lambda: calls.append("ops")):
        with TestClient(main.app):
            pass
    assert calls == ["jobs", "ops"]


def test_app_module_imports_without_deprecation_warnings():
    # fastapi's on_event emits DeprecationWarning at decoration time; importing
    # the app with warnings as errors proves nothing registers that way.
    result = subprocess.run(
        [sys.executable, "-W", "error::DeprecationWarning", "-c", "import voicerig.app.main"],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr[-800:]
