from __future__ import annotations

import json
from pathlib import Path
import zipfile

import pytest

from voicerig.engines.catalog import (
    CURRENT_ENGINE,
    ROST_DANISH_ENGINE_SPEC,
    defaults_for_engine,
    manifest_engine,
    package_compatibility,
    runtime_engine_spec,
    validate_engine_options,
)
from voicerig.model_contract import (
    ROST_DANISH_CFG_WEIGHT,
    ROST_DANISH_MIN_P,
    ROST_DANISH_REPETITION_PENALTY,
    ROST_DANISH_TOP_P,
)
from voicerig.profiles.package import build_package, validate_package


def _manifest(engine: dict) -> dict:
    return {
        "format": "modelrig-voice",
        "format_version": 1,
        "id": "portable-12345678",
        "name": "Portable",
        "language": "da",
        "engine": engine,
        "files": {
            "reference": "reference.wav",
            "conditioning": "conditioning.pt",
            "preview": "preview.wav",
        },
        "defaults": {"exaggeration": 0.5, "cfg_weight": 0.0, "temperature": 0.8},
    }


def test_current_engine_manifest_keeps_legacy_v1_shape():
    engine = manifest_engine(CURRENT_ENGINE)

    assert engine == {
        "name": CURRENT_ENGINE.name,
        "model": CURRENT_ENGINE.model,
        "revision": CURRENT_ENGINE.revision,
    }
    assert "options" not in engine
    assert defaults_for_engine(CURRENT_ENGINE, "da")["cfg_weight"] == 0.0


def test_rost_engine_manifest_records_all_nonshared_generation_options():
    engine = manifest_engine(ROST_DANISH_ENGINE_SPEC, include_options=True)
    options = validate_engine_options(engine)

    assert options == {
        "repetition_penalty": ROST_DANISH_REPETITION_PENALTY,
        "min_p": ROST_DANISH_MIN_P,
        "top_p": ROST_DANISH_TOP_P,
    }
    assert defaults_for_engine(ROST_DANISH_ENGINE_SPEC, "da")["cfg_weight"] == ROST_DANISH_CFG_WEIGHT


def test_engine_options_fail_closed_on_partial_unknown_bool_and_nonfinite_values():
    base = manifest_engine(ROST_DANISH_ENGINE_SPEC, include_options=True)

    partial = dict(base)
    partial["options"] = {"top_p": 0.95}
    with pytest.raises(ValueError, match="engine.options matcher ikke"):
        validate_engine_options(partial)

    unknown = dict(base)
    unknown["options"] = dict(base["options"], mystery=1.0)
    with pytest.raises(ValueError, match="engine.options matcher ikke"):
        validate_engine_options(unknown)

    boolean = dict(base)
    boolean["options"] = dict(base["options"], top_p=True)
    with pytest.raises(ValueError, match="top_p skal være et tal"):
        validate_engine_options(boolean)

    nonfinite = dict(base)
    nonfinite["options"] = dict(base["options"], min_p=float("nan"))
    with pytest.raises(ValueError, match="min_p ligger uden for"):
        validate_engine_options(nonfinite)


def test_unknown_engine_may_remain_legacy_but_cannot_smuggle_unvalidated_options():
    legacy = {"name": "future-engine", "model": "v1", "revision": "1" * 40}
    assert validate_engine_options(legacy) == {}

    with_options = dict(legacy, options={"temperature": 0.8})
    with pytest.raises(ValueError, match="kendt og eksakt pinnet"):
        validate_engine_options(with_options)


def test_package_compatibility_supports_current_and_pinned_rost_runtime():
    direct = package_compatibility(_manifest(manifest_engine(CURRENT_ENGINE)))
    assert direct["state"] == "direct"
    assert direct["runtime_supported"] is True
    assert runtime_engine_spec(_manifest(manifest_engine(CURRENT_ENGINE))) == CURRENT_ENGINE

    old_revision = manifest_engine(CURRENT_ENGINE)
    old_revision["revision"] = "0" * 40
    rebuild = package_compatibility(_manifest(old_revision))
    assert rebuild["state"] == "runtime-rebuild"
    assert rebuild["runtime_supported"] is True
    assert rebuild["can_rebuild_from_reference"] is True
    assert runtime_engine_spec(_manifest(old_revision)) == CURRENT_ENGINE

    rost_manifest = _manifest(manifest_engine(ROST_DANISH_ENGINE_SPEC, include_options=True))
    rost = package_compatibility(rost_manifest)
    assert rost["state"] == "direct"
    assert rost["runtime_supported"] is True
    assert rost["can_rebuild_from_reference"] is True
    assert runtime_engine_spec(rost_manifest) == ROST_DANISH_ENGINE_SPEC

    unknown_manifest = _manifest({"name": "future-engine", "model": "x", "revision": "1" * 40})
    unknown = package_compatibility(unknown_manifest)
    assert unknown["state"] == "unsupported"
    assert unknown["can_rebuild_from_reference"] is False
    assert runtime_engine_spec(unknown_manifest) is None


def test_build_package_can_record_pinned_rost_contract_without_changing_v1_payload_shape(tmp_path: Path):
    reference = tmp_path / "reference.wav"
    conditioning = tmp_path / "conditioning.pt"
    preview = tmp_path / "preview.wav"
    reference.write_bytes(b"RIFF-reference")
    conditioning.write_bytes(b"conditioning")
    preview.write_bytes(b"RIFF-preview")
    package = tmp_path / "rost-portable.mrvoice"

    build_package(
        "Røst Portable",
        "da",
        reference,
        conditioning,
        preview,
        package,
        engine_spec=ROST_DANISH_ENGINE_SPEC,
    )
    manifest = validate_package(package)

    assert manifest["engine"] == manifest_engine(ROST_DANISH_ENGINE_SPEC, include_options=True)
    assert manifest["defaults"] == defaults_for_engine(ROST_DANISH_ENGINE_SPEC, "da")
    with zipfile.ZipFile(package, "r") as zf:
        assert set(zf.namelist()) == {
            "manifest.json",
            "checksums.json",
            "reference.wav",
            "conditioning.pt",
            "preview.wav",
        }
        json.loads(zf.read("manifest.json"))
