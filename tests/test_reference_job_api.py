from __future__ import annotations

from fastapi.testclient import TestClient

import voicerig.app.job_api as job_api
import voicerig.app.main as main


def test_job_api_accepts_twenty_files_and_rejects_twenty_one(monkeypatch):
    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    monkeypatch.setattr(job_api, "prune_job_history", lambda: {"ok": True})
    captured = {}

    def create(name, language, install_in_modelrig, sources):
        captured["count"] = len(sources)
        return {
            "id": "a" * 32,
            "state": "queued",
            "name": name,
            "language": language,
            "progress": 0,
        }

    monkeypatch.setattr(job_api.job_manager, "create", create)
    client = TestClient(main.app)
    files20 = [
        ("files", (f"clip-{idx:02d}.wav", b"RIFF-test", "audio/wav"))
        for idx in range(20)
    ]
    response = client.post(
        "/api/jobs/voices",
        data={"name": "Tyve klip", "language": "da", "install_in_modelrig": "false"},
        files=files20,
    )
    assert response.status_code == 202
    assert captured["count"] == 20

    files21 = [
        ("files", (f"clip-{idx:02d}.wav", b"RIFF-test", "audio/wav"))
        for idx in range(21)
    ]
    rejected = client.post(
        "/api/jobs/voices",
        data={"name": "For mange", "language": "da", "install_in_modelrig": "false"},
        files=files21,
    )
    assert rejected.status_code == 400
    assert rejected.json()["detail"] == "Maksimalt 20 filer pr. stemme."


def test_reference_choice_endpoint_forwards_valid_choice(monkeypatch):
    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    captured = {}

    def choose_reference(job_id, choice):
        captured.update(job_id=job_id, choice=choice)
        return {
            "id": job_id,
            "state": "queued",
            "progress": 65,
            "reference_choices": None,
        }

    monkeypatch.setattr(job_api.job_manager, "choose_reference", choose_reference)
    client = TestClient(main.app)
    job_id = "b" * 32
    response = client.post(f"/api/jobs/{job_id}/reference", data={"choice": "3"})

    assert response.status_code == 200
    assert captured == {"job_id": job_id, "choice": 3}
    assert response.json()["job"]["state"] == "queued"


def test_reference_choice_endpoint_rejects_out_of_range_choice(monkeypatch):
    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    client = TestClient(main.app)
    response = client.post(f"/api/jobs/{'c' * 32}/reference", data={"choice": "5"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Ugyldigt referencevalg."
