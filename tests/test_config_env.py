from pathlib import Path

import voicerig.config as config


def test_local_env_fills_missing_values_without_overriding_session_env(tmp_path: Path, monkeypatch):
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "VOICERIG_TEST_EXISTING=from-file\nVOICERIG_TEST_NEW=from-file\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VOICERIG_TEST_EXISTING", "from-session")
    monkeypatch.delenv("VOICERIG_TEST_NEW", raising=False)

    assert config.load_local_env(dotenv) is True
    assert config.os.environ["VOICERIG_TEST_EXISTING"] == "from-session"
    assert config.os.environ["VOICERIG_TEST_NEW"] == "from-file"


def test_local_env_missing_file_is_a_noop(tmp_path: Path):
    assert config.load_local_env(tmp_path / "missing.env") is False
