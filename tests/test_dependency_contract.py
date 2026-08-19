from pathlib import Path
import tomllib

from voicerig.model_contract import (
    CHATTERBOX_SOURCE_REVISION,
    DIARIZATION_TORCH_VERSION,
    DIARIZATION_TORCHAUDIO_VERSION,
    DIARIZATION_TORCHCODEC_VERSION,
    PYANNOTE_PACKAGE_VERSION,
)


def _project():
    return tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))


def test_voice_extra_pins_verified_chatterbox_v3_source_revision():
    project = _project()
    voice = project["project"]["optional-dependencies"]["voice"]

    assert len(voice) == 1
    assert voice[0].startswith("chatterbox-tts @ git+https://github.com/resemble-ai/chatterbox.git@")
    assert voice[0].endswith(CHATTERBOX_SOURCE_REVISION)
    assert project["tool"]["hatch"]["metadata"]["allow-direct-references"] is True


def test_diarization_extra_pins_verified_pyannote_version():
    diarization = _project()["project"]["optional-dependencies"]["diarization"]
    assert diarization == [f"pyannote.audio=={PYANNOTE_PACKAGE_VERSION}"]


def test_windows_setup_pins_complete_cpu_diarization_stack():
    setup = Path("setup-windows.ps1").read_text(encoding="utf-8")
    assert f"torch=={DIARIZATION_TORCH_VERSION}" in setup
    assert f"torchaudio=={DIARIZATION_TORCHAUDIO_VERSION}" in setup
    assert f"torchcodec=={DIARIZATION_TORCHCODEC_VERSION}" in setup
    assert f"pyannote.audio=={PYANNOTE_PACKAGE_VERSION}" in setup
    assert "https://download.pytorch.org/whl/cpu" in setup


def test_dotenv_is_a_direct_runtime_dependency():
    dependencies = _project()["project"]["dependencies"]
    assert any(item.startswith("python-dotenv") for item in dependencies)
