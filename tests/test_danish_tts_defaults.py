from pathlib import Path

from voicerig.model_contract import tts_defaults
from voicerig.profiles.package import build_package, validate_package


def test_danish_tuning_is_accent_minimizing_and_other_controls_stay_stable():
    assert tts_defaults("da") == {
        "exaggeration": 0.5,
        "cfg_weight": 0.0,
        "temperature": 0.8,
    }
    assert tts_defaults("da-DK") == tts_defaults("da")


def test_non_danish_languages_keep_chatterbox_defaults():
    assert tts_defaults("sv") == {
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "temperature": 0.8,
    }
    assert tts_defaults("de") == tts_defaults("sv")


def test_new_voice_package_persists_danish_tuning(tmp_path: Path):
    reference = tmp_path / "reference.wav"
    conditioning = tmp_path / "conditioning.pt"
    preview = tmp_path / "preview.wav"
    package = tmp_path / "danish.mrvoice"
    reference.write_bytes(b"RIFF-reference")
    conditioning.write_bytes(b"conditioning")
    preview.write_bytes(b"RIFF-preview")

    build_package("Dansk", "da", reference, conditioning, preview, package)
    manifest = validate_package(package)

    assert manifest["language"] == "da"
    assert manifest["defaults"] == tts_defaults("da")
