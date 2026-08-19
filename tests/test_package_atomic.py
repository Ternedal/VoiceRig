from __future__ import annotations

from pathlib import Path

import pytest

import voicerig.profiles.package as package_module


def _artifacts(tmp_path: Path) -> tuple[Path, Path, Path]:
    reference = tmp_path / "reference.wav"
    conditioning = tmp_path / "conditioning.pt"
    preview = tmp_path / "preview.wav"
    reference.write_bytes(b"RIFF-reference")
    conditioning.write_bytes(b"conditioning")
    preview.write_bytes(b"RIFF-preview")
    return reference, conditioning, preview


def test_failed_new_package_validation_preserves_existing_profile(tmp_path: Path, monkeypatch):
    reference, conditioning, preview = _artifacts(tmp_path)
    output = tmp_path / "anders.mrvoice"
    old_bytes = b"existing-known-good-profile"
    output.write_bytes(old_bytes)

    def reject_new_package(_path: Path):
        raise ValueError("injected validation failure")

    monkeypatch.setattr(package_module, "validate_package", reject_new_package)

    with pytest.raises(ValueError, match="injected validation failure"):
        package_module.build_package(
            "Anders",
            "da",
            reference,
            conditioning,
            preview,
            output,
        )

    assert output.read_bytes() == old_bytes
    assert not (tmp_path / "anders.mrvoice.tmp").exists()


def test_successful_rebuild_atomically_replaces_existing_profile(tmp_path: Path):
    reference, conditioning, preview = _artifacts(tmp_path)
    output = tmp_path / "anders.mrvoice"
    output.write_bytes(b"old-profile")

    package_module.build_package(
        "Anders",
        "da",
        reference,
        conditioning,
        preview,
        output,
    )

    manifest = package_module.validate_package(output)
    assert manifest["name"] == "Anders"
    assert output.read_bytes() != b"old-profile"
    assert not (tmp_path / "anders.mrvoice.tmp").exists()
