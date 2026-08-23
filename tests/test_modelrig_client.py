from pathlib import Path

import voicerig.modelrig.client as client
from voicerig.modelrig.client import install_local, status


def test_local_install_copies_package_and_sets_default(tmp_path: Path, monkeypatch):
    voices = tmp_path / "voices"
    monkeypatch.setenv("MODELRIG_VOICES_DIR", str(voices))
    package = tmp_path / "anders.mrvoice"
    package.write_bytes(b"profile")

    result = install_local(package)

    assert (voices / "anders.mrvoice").read_bytes() == b"profile"
    assert (voices / "default.txt").read_text().strip() == "anders.mrvoice"
    assert result["mode"] == "local"


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_modelrig_status_reports_authenticated_voicerig_provider(monkeypatch):
    seen = {}

    def fake_get(url, headers, timeout):
        seen.update(url=url, headers=headers, timeout=timeout)
        return _Response(
            200,
            {
                "ok": True,
                "checks": {
                    "tts": {
                        "ok": True,
                        "provider": "voicerig",
                        "voice": "Anders",
                        "package": "anders.mrvoice",
                        "device": "cuda",
                    }
                },
            },
        )

    monkeypatch.setattr(client.httpx, "get", fake_get)

    result = status("http://127.0.0.1:8080", token="secret")

    assert result["ok"] is True
    assert result["reachable"] is True
    assert result["tts"]["provider"] == "voicerig"
    assert result["tts"]["package"] == "anders.mrvoice"
    assert seen["url"].endswith("/api/v1/health/full")
    assert seen["headers"]["Authorization"] == "Bearer secret"


def test_modelrig_status_distinguishes_bad_token(monkeypatch):
    monkeypatch.setattr(
        client.httpx,
        "get",
        lambda *args, **kwargs: _Response(401, {"detail": "unauthorized"}),
    )

    result = status("http://127.0.0.1:8080", token="bad")

    assert result["ok"] is False
    assert result["reachable"] is True
    assert result["http_status"] == 401
    assert "MODELRIG_TOKEN" in result["detail"]


def test_modelrig_status_reports_tts_degraded_separately(monkeypatch):
    monkeypatch.setattr(
        client.httpx,
        "get",
        lambda *args, **kwargs: _Response(
            200,
            {"ok": True, "checks": {"tts": {"ok": False, "provider": "piper", "detail": "voice missing"}}},
        ),
    )

    result = status("http://127.0.0.1:8080")

    assert result["reachable"] is True
    assert result["ok"] is False
    assert result["tts"]["provider"] == "piper"
    assert result["detail"] == "ModelRig er online, men TTS er ikke klar."
