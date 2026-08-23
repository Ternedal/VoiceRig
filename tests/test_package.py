from pathlib import Path
import json
import zipfile

import pytest

import voicerig.profiles.package as package_module
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


def test_backup_references_are_packaged_and_covered_by_checksums(tmp_path: Path):
    ref = tmp_path / "reference.wav"; ref.write_bytes(b"RIFF-reference")
    cond = tmp_path / "conditioning.pt"; cond.write_bytes(b"conditioning")
    preview = tmp_path / "preview.wav"; preview.write_bytes(b"RIFF-preview")
    alt1 = tmp_path / "alt1.wav"; alt1.write_bytes(b"RIFF-alt-1")
    alt2 = tmp_path / "alt2.wav"; alt2.write_bytes(b"RIFF-alt-2")
    package = tmp_path / "portable.mrvoice"

    build_package("Portable", "da", ref, cond, preview, package, alternatives=[alt1, alt2])
    validate_package(package)

    with zipfile.ZipFile(package, "r") as zf:
        names = set(zf.namelist())
        checksums = json.loads(zf.read("checksums.json"))
    assert "references/candidate_01.wav" in names
    assert "references/candidate_02.wav" in names
    assert set(checksums) == names - {"manifest.json", "checksums.json"}


def test_rejects_path_traversal(tmp_path: Path):
    package = tmp_path / "evil.mrvoice"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("../evil", b"x")
    with pytest.raises(ValueError, match="Ugyldig sti"):
        validate_package(package)


def test_rejects_path_like_manifest_id_before_runtime_materialization(tmp_path: Path):
    package = tmp_path / "bad-id.mrvoice"
    manifest = _manifest(id="../../escape")
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("checksums.json", "{}")
        zf.writestr("reference.wav", b"a")
        zf.writestr("conditioning.pt", b"b")
        zf.writestr("preview.wav", b"c")
    with pytest.raises(ValueError, match="Manifestets id"):
        validate_package(package)


def test_rejects_undocumented_reference_payload_name(tmp_path: Path):
    package = tmp_path / "bad-reference-name.mrvoice"
    with zipfile.ZipFile(package, "w") as zf:
        zf.writestr("manifest.json", "{}")
        zf.writestr("checksums.json", "{}")
        zf.writestr("reference.wav", b"a")
        zf.writestr("conditioning.pt", b"b")
        zf.writestr("preview.wav", b"c")
        zf.writestr("references/arbitrary.wav", b"not allowed")
    with pytest.raises(ValueError, match="Ukendt fil"):
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
        zf.writestr("reference.wav", b"\0" * (17 * 1024 * 1024))
    with pytest.raises(ValueError, match="reference.wav er for stor"):
        validate_package(package)


def test_rejects_aggregate_uncompressed_size_over_global_limit():
    sizes = {
        "manifest.json": 1,
        "checksums.json": 1,
        "conditioning.pt": 64 * 1024 * 1024,
        "reference.wav": 16 * 1024 * 1024,
        "preview.wav": 16 * 1024 * 1024,
        "references/candidate_01.wav": 16 * 1024 * 1024,
        "references/candidate_02.wav": 16 * 1024 * 1024,
    }
    infos = []
    for name, size in sizes.items():
        info = zipfile.ZipInfo(name)
        info.file_size = size
        infos.append(info)

    with pytest.raises(ValueError, match="for stor efter udpakning"):
        package_module._validate_archive_shape(infos)


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
