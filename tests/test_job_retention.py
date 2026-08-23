from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from voicerig.app.job_retention import prune_job_history


def _write_job(root: Path, job_id: str, state: str, updated: datetime) -> Path:
    payload = {
        "id": job_id,
        "state": state,
        "stage": state,
        "progress": 65 if state == "needs_reference" else 40,
        "message": state,
        "created_at": updated.isoformat(),
        "updated_at": updated.isoformat(),
        "speaker_choices": [{"anchor": "0:1.0", "preview_wav_base64": "PRIVATE"}] if state == "needs_speaker" else None,
        "speaker_anchor": None,
        "reference_choices": [{"choice": 1, "preview_wav_base64": "PRIVATE"}] if state == "needs_reference" else None,
        "reference_choice": None,
    }
    path = root / f"{job_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_expired_speaker_job_drops_private_inputs(tmp_path: Path):
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    job_id = "a" * 32
    _write_job(tmp_path, job_id, "needs_speaker", now - timedelta(days=8))
    work = tmp_path / job_id
    work.mkdir()
    (work / "input_00.wav").write_bytes(b"private audio")

    result = prune_job_history(root=tmp_path, now=now, paused_max_age_days=7)

    payload = json.loads((tmp_path / f"{job_id}.json").read_text(encoding="utf-8"))
    assert result["expired_paused"] == 1
    assert payload["state"] == "cancelled"
    assert payload["speaker_choices"] is None
    assert payload["reference_choices"] is None
    assert not work.exists()


def test_expired_reference_job_drops_private_inputs_and_auditions(tmp_path: Path):
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    job_id = "c" * 32
    _write_job(tmp_path, job_id, "needs_reference", now - timedelta(days=8))
    work = tmp_path / job_id
    work.mkdir()
    (work / "input_00.wav").write_bytes(b"private audio")

    result = prune_job_history(root=tmp_path, now=now, paused_max_age_days=7)

    payload = json.loads((tmp_path / f"{job_id}.json").read_text(encoding="utf-8"))
    assert result["expired_paused"] == 1
    assert payload["state"] == "cancelled"
    assert payload["progress"] == 65
    assert payload["reference_choices"] is None
    assert payload["reference_choice"] is None
    assert "Kildeklippene er slettet" in payload["message"]
    assert not work.exists()


def test_terminal_history_is_bounded_by_count(tmp_path: Path):
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    ids = ["1" * 32, "2" * 32, "3" * 32]
    for index, job_id in enumerate(ids):
        _write_job(tmp_path, job_id, "succeeded", now - timedelta(hours=index))

    result = prune_job_history(
        root=tmp_path,
        now=now,
        max_terminal_jobs=2,
        terminal_max_age_days=30,
    )

    assert result["deleted_terminal"] == 1
    assert (tmp_path / f"{ids[0]}.json").exists()
    assert (tmp_path / f"{ids[1]}.json").exists()
    assert not (tmp_path / f"{ids[2]}.json").exists()


def test_active_job_is_never_pruned(tmp_path: Path):
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    job_id = "b" * 32
    _write_job(tmp_path, job_id, "running", now - timedelta(days=90))
    work = tmp_path / job_id
    work.mkdir()
    (work / "input_00.wav").write_bytes(b"private audio")

    prune_job_history(root=tmp_path, now=now, terminal_max_age_days=1)

    assert (tmp_path / f"{job_id}.json").exists()
    assert work.exists()
