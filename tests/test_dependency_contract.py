from pathlib import Path
import tomllib


VERIFIED_CHATTERBOX_REVISION = "5de7a54aa4e5e2baadb0182dde554908b48b85c2"


def test_voice_extra_pins_verified_chatterbox_v3_source_revision():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    voice = project["project"]["optional-dependencies"]["voice"]

    assert len(voice) == 1
    assert voice[0].startswith("chatterbox-tts @ git+https://github.com/resemble-ai/chatterbox.git@")
    assert voice[0].endswith(VERIFIED_CHATTERBOX_REVISION)


def test_dotenv_is_a_direct_runtime_dependency():
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    assert any(item.startswith("python-dotenv") for item in dependencies)
