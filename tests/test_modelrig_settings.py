import json
from pathlib import Path

import pytest
from fastapi import HTTPException

import voicerig.app.ops_api as ops_api
import voicerig.config as config


def test_modelrig_token_configuration_never_returns_secret(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(config, "_REPO_ROOT", tmp_path)
    monkeypatch.delenv("MODELRIG_TOKEN", raising=False)
    (tmp_path / ".env.example").write_text(
        "MODELRIG_TOKEN=\nVOICERIG_ALLOW_LAN=0\n",
        encoding="utf-8",
    )
    seen_tokens = []

    def fake_status(_base_url, token=None):
        seen_tokens.append(token)
        return {
            "ok": token == "device-secret",
            "reachable": True,
            "http_status": 200 if token else 401,
            "detail": None if token else "auth required",
        }

    monkeypatch.setattr(ops_api, "modelrig_status", fake_status)

    result = ops_api.configure_modelrig_token("device-secret")

    assert result["ok"] is True
    assert result["token_configured"] is True
    assert result["modelrig"]["ok"] is True
    assert seen_tokens == ["device-secret"]
    assert ops_api.modelrig_config() == {"ok": True, "token_configured": True}
    assert "device-secret" not in json.dumps(result)
    assert config.modelrig_token() == "device-secret"

    cleared = ops_api.configure_modelrig_token("")
    assert cleared["token_configured"] is False
    assert config.modelrig_token() is None
    assert "device-secret" not in json.dumps(cleared)


def test_modelrig_token_configuration_rejects_multiline_secret(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr(config, "_REPO_ROOT", tmp_path)
    monkeypatch.delenv("MODELRIG_TOKEN", raising=False)

    with pytest.raises(HTTPException) as exc:
        ops_api.configure_modelrig_token("line1\nline2")

    assert exc.value.status_code == 422
    assert "line1" not in str(exc.value.detail)
