from __future__ import annotations

from pathlib import Path
import zipfile

import pytest

from voicerig.engines.catalog import ROST_DANISH_ENGINE_SPEC, manifest_engine
from voicerig.profiles.migration import migration_plan, rebuild_package_for_engine
from voicerig.profiles.package import build_package, validate_package


def _source_package(tmp_path: Path) -> Path:
    reference = tmp_path / "reference.wav"
    conditioning = tmp_path / "conditioning.pt"
    preview = tmp_path / "preview.wav"
    alternative = tmp_path / "alternative.wav"
    alternative2 = tmp_path / "alternative2.wav"
    reference.write_bytes(b"RIFF-primary-reference")
    conditioning.write_bytes(b"current-conditioning")
    preview.write_bytes(b"RIFF-current-preview")
    alternative.write_bytes(b"RIFF-backup-reference")
    alternative2.write_bytes(b"RIFF-best-rost-reference")
    package = tmp_path / "voice.mrvoice"
    return build_package(
        "Anders",
        "da",
        reference,
        conditioning,
        preview,
        package,
        alternatives=[alternative, alternative2],
        voice_id="anders-stable-1234",
    )


def test_migration_plan_is_non_mutating_and_explicit(tmp_path: Path):
    package = _source_package(tmp_path)
    before = package.read_bytes()

    plan = migration_plan(package, ROST_DANISH_ENGINE_SPEC)

    assert package.read_bytes() == before
    assert plan["voice_id"] == "anders-stable-1234"
    assert plan["target_engine"] == manifest_engine(
        ROST_DANISH_ENGINE_SPEC,
        include_options=True,
    )
    assert plan["preserves_voice_id"] is True
    assert plan["preserves_reference"] is True
    assert plan["reference_count"] == 3
    assert plan["backup_reference_count"] == 2
    assert plan["requires_new_conditioning"] is True
    assert plan["requires_new_preview"] is True


def test_in_place_engine_rebuild_preserves_identity_and_reference_audio(tmp_path: Path):
    package = _source_package(tmp_path)
    source_manifest = validate_package(package)
    with zipfile.ZipFile(package, "r") as zf:
        primary_before = zf.read("reference.wav")
        backup_before = zf.read("references/candidate_01.wav")
        backup2_before = zf.read("references/candidate_02.wav")

    conditioning = tmp_path / "rost-conditioning.pt"
    preview = tmp_path / "rost-preview.wav"
    conditioning.write_bytes(b"rost-conditioning")
    preview.write_bytes(b"RIFF-rost-preview")

    rebuilt = rebuild_package_for_engine(
        package,
        ROST_DANISH_ENGINE_SPEC,
        conditioning,
        preview,
        package,
    )

    assert rebuilt == package
    manifest = validate_package(package)
    assert manifest["id"] == source_manifest["id"]
    assert manifest["name"] == source_manifest["name"]
    assert manifest["language"] == source_manifest["language"]
    assert manifest["engine"] == manifest_engine(ROST_DANISH_ENGINE_SPEC, include_options=True)
    with zipfile.ZipFile(package, "r") as zf:
        assert zf.read("reference.wav") == primary_before
        assert zf.read("references/candidate_01.wav") == backup_before
        assert zf.read("references/candidate_02.wav") == backup2_before
        assert zf.read("conditioning.pt") == b"rost-conditioning"
        assert zf.read("preview.wav") == b"RIFF-rost-preview"


def test_in_place_rebuild_can_promote_reference_three_and_keep_others_as_backups(tmp_path: Path):
    package = _source_package(tmp_path)
    source_manifest = validate_package(package)
    with zipfile.ZipFile(package, "r") as zf:
        original_primary = zf.read("reference.wav")
        original_second = zf.read("references/candidate_01.wav")
        original_third = zf.read("references/candidate_02.wav")

    conditioning = tmp_path / "rost-conditioning-selected.pt"
    preview = tmp_path / "rost-preview-selected.wav"
    conditioning.write_bytes(b"rost-conditioning-selected")
    preview.write_bytes(b"RIFF-rost-preview-selected")

    rebuild_package_for_engine(
        package,
        ROST_DANISH_ENGINE_SPEC,
        conditioning,
        preview,
        package,
        reference_index=2,
    )

    manifest = validate_package(package)
    assert manifest["id"] == source_manifest["id"]
    assert manifest["engine"] == manifest_engine(ROST_DANISH_ENGINE_SPEC, include_options=True)
    with zipfile.ZipFile(package, "r") as zf:
        assert zf.read("reference.wav") == original_third
        assert zf.read("references/candidate_01.wav") == original_primary
        assert zf.read("references/candidate_02.wav") == original_second
        assert zf.read("conditioning.pt") == b"rost-conditioning-selected"
        assert zf.read("preview.wav") == b"RIFF-rost-preview-selected"


def test_invalid_reference_index_leaves_package_untouched(tmp_path: Path):
    package = _source_package(tmp_path)
    before = package.read_bytes()
    conditioning = tmp_path / "rost-conditioning.pt"
    preview = tmp_path / "rost-preview.wav"
    conditioning.write_bytes(b"rost-conditioning")
    preview.write_bytes(b"RIFF-rost-preview")

    with pytest.raises(ValueError, match="valgte reference findes ikke"):
        rebuild_package_for_engine(
            package,
            ROST_DANISH_ENGINE_SPEC,
            conditioning,
            preview,
            package,
            reference_index=5,
        )

    assert package.read_bytes() == before
    validate_package(package)


def test_failed_in_place_rebuild_leaves_known_good_package_untouched(tmp_path: Path):
    package = _source_package(tmp_path)
    before = package.read_bytes()
    preview = tmp_path / "rost-preview.wav"
    preview.write_bytes(b"RIFF-rost-preview")
    missing_conditioning = tmp_path / "missing-conditioning.pt"

    with pytest.raises(FileNotFoundError):
        rebuild_package_for_engine(
            package,
            ROST_DANISH_ENGINE_SPEC,
            missing_conditioning,
            preview,
            package,
        )

    assert package.read_bytes() == before
    validate_package(package)
