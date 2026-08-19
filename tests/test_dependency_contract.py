from pathlib import Path
import tomllib

from voicerig.model_contract import CHATTERBOX_SOURCE_REVISION


def _project():
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))


def test_voice_extra_pins_verified_chatterbox_v3_source_revision():
    project = _project()
    voice = project["project"]["optional-dependencies"]["voice"]

    assert len(voice) == 1
    assert voice[0].startswith("chatterbox-tts @ git+https://github.com/resemble-ai/chatterbox.git@")
    assert voice[0].endswith(CHATTERBOX_SOURCE_REVISION)
    assert project["tool"]["hatch"]["metadata"]["allow-direct-references"] is True


def test_dotenv_is_a_direct_runtime_dependency():
    dependencies = _project()["project"]["dependencies"]
    assert any(item.startswith("python-dotenv") for item in dependencies)
