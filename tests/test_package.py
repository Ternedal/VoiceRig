from pathlib import Path
import json
import zipfile

import pytest

from voicerig.profiles.package import build_package, validate_package


def _manifest(**overrides):
    value = {
        "format": "modelrig-voice",
        "format_version": 1,
        "id": "test-12345678",
        "name": "Test",
        "language": "da",
        "engine": {"name": "chatterbox-multilingual", "model": "v3"},
        "files": {
            "reference": "reference.wav",
            "conditioning": "conditioning.pt",
            "preview": "preview.wav",
        },
        "defaults": {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8},
    }
    value.update(overrides)
    return value


def test_build_and_validate_package(tmp_path: Path):
    ref = tmp_path / "reference.wav"; ref.write_bytes(b"RIFF-reference")
    cond = tmp_path / "conditioning.pt"; cond.write_bytes(b"conditioning")
    preview = tmp_path / "preview.wav"; preview.write_bytes(b"RIFF-preview")
    package = tmp_path / "anders.mrvoice"

    build_package("Anders", "da", ref, cond, preview, package)
    manifest = validate_package(package)

    assert manifest["format"] == "modelrig-voice"
    assert manifest["format_version"] == 1
    assert manifest["name"] == "Anders"
    assert manifest["language"] == "da"
    assert manifest["engine"]["model"] == "v3"


def test_rejects_path_traversal(tmp_path: Path):
    package = tmp_path / "evil.mrvoice"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("../evil", b"x")
    with pytest.raises(ValueError, match="Ugyldig sti"):
        validate_package(package)


def test_rejects_incomplete_checksums(tmp_path: Path):
    package = tmp_path / "bad.mrvoice"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("manifest.json", json.dumps(_manifest()))
        zf.writestr("checksums.json", "{}")
        zf.writestr("reference.wav", b"a")
        zf.writestr("conditioning.pt", b"b")
        zf.writestr("preview.wav", b"c")
    with pytest.raises(ValueError, match="Checksums"):
        validate_package(package)


def test_rejects_unknown_payload(tmp_path: Path):
    package = tmp_path / "bad.mrvoice"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("checksums.json", "{}")
        zf.writestr("reference.wav", b"a")
        zf.writestr("conditioning.pt", b"b")
        zf.writestr("preview.wav", b"c")
        zf.writestr("run.exe", b"nope")
    with pytest.raises(ValueError, match="Ukendt fil"):
        validate_package(package)


def test_rejects_zip_bomb_sized_reference_before_payload_read(tmp_path: Path):
    package = tmp_path / "oversized.mrvoice"
    with zipfile.ZipFile(package, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Highly compressible content keeps the archive tiny while its declared
        # uncompressed size exceeds the 16 MiB WAV contract.
        zf.writestr("reference.wav", b"\0" * (17 * 1024 * 1024))
    with pytest.raises(ValueError, match="reference.wav er for stor"):
        validate_package(package)


def test_rejects_nonfinite_tts_default(tmp_path: Path):
    package = tmp_path / "nan.mrvoice"
    manifest = _manifest(defaults={"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": float("nan")})
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest, allow_nan=True))
        zf.writestr("checksums.json", "{}")
        zf.writestr("reference.wav", b"a")
        zf.writestr("conditioning.pt", b"b")
        zf.writestr("preview.wav", b"c")
    with pytest.raises(ValueError, match="Ugyldig JSON-konstant"):
        validate_package(package)


def test_rejects_out_of_range_tts_default(tmp_path: Path):
    package = tmp_path / "range.mrvoice"
    manifest = _manifest(defaults={"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 99.0})
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("checksums.json", "{}")
        zf.writestr("reference.wav", b"a")
        zf.writestr("conditioning.pt", b"b")
        zf.writestr("preview.wav", b"c")
    with pytest.raises(ValueError, match="temperature ligger uden for"):
        validate_package(package)
