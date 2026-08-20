from __future__ import annotations

from types import SimpleNamespace

import voicerig.source_control as source_control


def test_source_status_reports_revision_branch_dirty_state_and_root(monkeypatch):
    outputs = {
        ("rev-parse", "HEAD"): "abc123\n",
        ("branch", "--show-current"): "agent/voicerig-mvp\n",
        ("status", "--porcelain"): " M README.md\n",
    }

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(returncode=0, stdout=outputs[tuple(cmd[1:])], stderr="")

    monkeypatch.setattr(source_control.subprocess, "run", fake_run)
    status = source_control.source_status()

    assert status["revision"] == "abc123"
    assert status["branch"] == "agent/voicerig-mvp"
    assert status["dirty"] is True
    assert status["available"] is True
    assert status["root"] == str(source_control.repo_root().resolve())


def test_source_status_fails_softly_without_git(monkeypatch):
    def missing(*args, **kwargs):
        raise OSError("git missing")

    monkeypatch.setattr(source_control.subprocess, "run", missing)
    status = source_control.source_status()

    assert status["available"] is False
    assert status["revision"] is None
    assert status["dirty"] is None
    assert status["root"] == str(source_control.repo_root().resolve())
