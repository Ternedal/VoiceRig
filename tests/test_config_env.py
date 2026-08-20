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


def test_explicit_data_dir_wins(tmp_path: Path, monkeypatch):
    target = tmp_path / "explicit"
    monkeypatch.setenv("VOICERIG_DATA_DIR", str(target))

    assert config.data_dir() == target.resolve()
    assert target.is_dir()


def test_legacy_repo_data_is_migrated_to_stable_default(tmp_path: Path, monkeypatch):
    legacy = tmp_path / "legacy"
    stable = tmp_path / "stable"
    legacy.mkdir()
    (legacy / "model-readiness.json").write_text("ready", encoding="utf-8")
    monkeypatch.delenv("VOICERIG_DATA_DIR", raising=False)
    monkeypatch.setattr(config, "_legacy_repo_data_dir", lambda: legacy)
    monkeypatch.setattr(config, "_default_data_dir", lambda: stable)

    resolved = config.data_dir()

    assert resolved == stable.resolve()
    assert (stable / "model-readiness.json").read_text(encoding="utf-8") == "ready"
    assert not legacy.exists()


def test_legacy_env_default_is_migrated_instead_of_overriding_stable_storage(
    tmp_path: Path, monkeypatch
):
    legacy = tmp_path / "legacy"
    stable = tmp_path / "stable"
    legacy.mkdir()
    (legacy / "jobs.json").write_text("legacy-job", encoding="utf-8")
    monkeypatch.setenv("VOICERIG_DATA_DIR", ".\\voicerig-data")
    monkeypatch.setattr(config, "_legacy_repo_data_dir", lambda: legacy)
    monkeypatch.setattr(config, "_default_data_dir", lambda: stable)

    resolved = config.data_dir()

    assert resolved == stable.resolve()
    assert (stable / "jobs.json").read_text(encoding="utf-8") == "legacy-job"
    assert not legacy.exists()
