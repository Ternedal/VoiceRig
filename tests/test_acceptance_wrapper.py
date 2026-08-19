from __future__ import annotations

import json
import sys
from pathlib import Path

import voicerig.acceptance_wrapper as acceptance


def _clean_source(revision: str = "a" * 40) -> dict:
    return {
        "revision": revision,
        "branch": "agent/voicerig-mvp",
        "dirty": False,
        "available": True,
    }


def test_dirty_checkout_fails_before_physical_validator(tmp_path: Path, monkeypatch):
    report = tmp_path / "report.json"
    source = _clean_source()
    source["dirty"] = True
    monkeypatch.setattr(acceptance, "source_status", lambda: source)
    monkeypatch.setattr(sys, "argv", ["acceptance", "--report", str(report)])

    called = {"inner": False}

    def inner():
        called["inner"] = True
        return 0

    monkeypatch.setattr(acceptance.rig_validation, "main", inner)

    assert acceptance.main() == 1
    assert called["inner"] is False
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["stage"] == "source-identity"
    assert payload["source_evidence"]["checkout"]["dirty"] is True
    assert any("clean checkout" in item for item in payload["blockers"])


def test_full_e2e_rejects_service_running_different_revision(tmp_path: Path, monkeypatch):
    report = tmp_path / "report.json"
    checkout = _clean_source("a" * 40)
    monkeypatch.setattr(acceptance, "source_status", lambda: checkout)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "acceptance",
            "--source",
            "voice.wav",
            "--voicerig-url",
            "http://127.0.0.1:8765",
            "--report",
            str(report),
        ],
    )

    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "ready": True,
                "pid": 123,
                "source": {
                    "revision": "b" * 40,
                    "branch": "agent/voicerig-mvp",
                    "dirty": False,
                    "available": True,
                },
            }

    monkeypatch.setattr(acceptance.httpx, "get", lambda _url, timeout: Response())
    monkeypatch.setattr(
        acceptance.rig_validation,
        "main",
        lambda: (_ for _ in ()).throw(AssertionError("inner validator must not run")),
    )

    assert acceptance.main() == 1
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["source_evidence"]["same_revision"] is False
    assert any("samme Git HEAD" in item for item in payload["blockers"])


def test_clean_full_e2e_augments_normal_report_with_source_evidence(tmp_path: Path, monkeypatch):
    report = tmp_path / "report.json"
    revision = "c" * 40
    checkout = _clean_source(revision)
    monkeypatch.setattr(acceptance, "source_status", lambda: checkout)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "acceptance",
            "--source",
            "voice.wav",
            "--voicerig-url",
            "http://127.0.0.1:8765",
            "--report",
            str(report),
        ],
    )

    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {
                "ready": True,
                "pid": 456,
                "source": {
                    "revision": revision,
                    "branch": "agent/voicerig-mvp",
                    "dirty": False,
                    "available": True,
                },
            }

    monkeypatch.setattr(acceptance.httpx, "get", lambda _url, timeout: Response())

    def inner():
        report.write_text(json.dumps({"ok": True, "stage": "complete"}), encoding="utf-8")
        return 0

    monkeypatch.setattr(acceptance.rig_validation, "main", inner)

    assert acceptance.main() == 0
    payload = json.loads(report.read_text(encoding="utf-8"))
    evidence = payload["source_evidence"]
    assert evidence["checkout"]["revision"] == revision
    assert evidence["service"]["pid"] == 456
    assert evidence["service"]["source"]["revision"] == revision
    assert evidence["same_revision"] is True
