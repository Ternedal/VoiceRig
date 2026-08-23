from pathlib import Path

import pytest

import voicerig.app.pipeline as pipeline
from voicerig.engines.catalog import CURRENT_ENGINE, ROST_DANISH_ENGINE_SPEC
from voicerig.languages import (
    accent_choices,
    engine_language_id,
    normalize_build_locale,
    preview_text,
    public_voice_options,
    validate_accent,
)
from voicerig.profiles.migration import rebuild_package_for_engine
from voicerig.profiles.package import build_package, validate_package


def _payloads(tmp_path: Path):
    reference = tmp_path / "reference.wav"
    conditioning = tmp_path / "conditioning.pt"
    preview = tmp_path / "preview.wav"
    reference.write_bytes(b"RIFF-reference")
    conditioning.write_bytes(b"conditioning")
    preview.write_bytes(b"RIFF-preview")
    return reference, conditioning, preview


def test_locale_maps_to_documented_engine_language_id():
    assert engine_language_id("da-DK") == "da"
    assert engine_language_id("en-US") == "en"
    assert engine_language_id("en-GB") == "en"
    assert engine_language_id("de-DE") == "de"
    assert engine_language_id("pt-BR") == "pt"
    assert normalize_build_locale("en-us") == "en-US"
    assert normalize_build_locale("DA") == "da"


def test_unknown_locale_and_language_fail_closed():
    with pytest.raises(ValueError, match="Locale"):
        normalize_build_locale("en-ZZ")
    with pytest.raises(ValueError, match="understøttes ikke"):
        engine_language_id("xx-XX")


def test_us_regional_accents_are_explicit_reference_led_profiles():
    accents = dict(accent_choices("en-US"))
    assert accents["general-american"] == "General American"
    assert accents["southern-us"] == "Southern US"
    assert accents["texas-south-central"] == "Texas / South Central"
    assert accents["new-york-city"] == "New York City"
    assert accents["new-england-boston"] == "New England / Boston"
    assert accents["midwest-great-lakes"] == "Midwest / Great Lakes"
    assert accents["west-coast-california"] == "West Coast / California"
    assert validate_accent("en-US", "new-york-city") == "new-york-city"
    assert validate_accent("en-US", "") is None

    with pytest.raises(ValueError, match="understøttes ikke"):
        validate_accent("en-GB", "new-york-city")
    with pytest.raises(ValueError, match="understøttes ikke"):
        validate_accent("de-DE", "southern-us")


def test_public_options_keep_locale_separate_from_engine_language():
    payload = public_voice_options()
    us = next(item for item in payload["locales"] if item["code"] == "en-US")
    uk = next(item for item in payload["locales"] if item["code"] == "en-GB")
    german = next(item for item in payload["locales"] if item["code"] == "de-DE")

    assert payload["default_locale"] == "da-DK"
    assert payload["accent_semantics"] == "reference-led-metadata"
    assert us["language_id"] == "en"
    assert uk["language_id"] == "en"
    assert german["language_id"] == "de"
    assert any(item["code"] == "southern-us" for item in us["accents"])
    assert uk["accents"] == []


def test_preview_text_follows_language_instead_of_always_being_danish():
    assert preview_text("da-DK").startswith("Hej")
    assert preview_text("en-US").startswith("Hello")
    assert preview_text("de-DE").startswith("Hallo")


def test_danish_locale_uses_rost_while_other_locales_keep_multilingual_engine():
    assert pipeline._build_engine_spec("da") == ROST_DANISH_ENGINE_SPEC
    assert pipeline._build_engine_spec("da-DK") == ROST_DANISH_ENGINE_SPEC
    assert pipeline._build_engine_spec("en-US") == CURRENT_ENGINE
    assert pipeline._build_engine_spec("en-GB") == CURRENT_ENGINE
    assert pipeline._build_engine_spec("de-DE") == CURRENT_ENGINE


def test_mrvoice_persists_optional_us_accent_without_breaking_legacy_shape(tmp_path: Path):
    reference, conditioning, preview = _payloads(tmp_path)
    accented = tmp_path / "accented.mrvoice"
    legacy = tmp_path / "legacy.mrvoice"

    build_package(
        "US voice",
        "en-US",
        reference,
        conditioning,
        preview,
        accented,
        accent="southern-us",
    )
    build_package(
        "Legacy voice",
        "en",
        reference,
        conditioning,
        preview,
        legacy,
    )

    accented_manifest = validate_package(accented)
    legacy_manifest = validate_package(legacy)
    assert accented_manifest["language"] == "en-US"
    assert accented_manifest["accent"] == "southern-us"
    assert "accent" not in legacy_manifest


def test_mrvoice_rejects_accent_that_does_not_match_locale(tmp_path: Path):
    reference, conditioning, preview = _payloads(tmp_path)
    with pytest.raises(ValueError, match="understøttes ikke"):
        build_package(
            "Wrong accent",
            "en-GB",
            reference,
            conditioning,
            preview,
            tmp_path / "wrong.mrvoice",
            accent="southern-us",
        )


def test_engine_migration_preserves_locale_and_accent(tmp_path: Path):
    reference, conditioning, preview = _payloads(tmp_path)
    source = tmp_path / "source.mrvoice"
    target = tmp_path / "target.mrvoice"
    new_conditioning = tmp_path / "new-conditioning.pt"
    new_preview = tmp_path / "new-preview.wav"
    new_conditioning.write_bytes(b"new-conditioning")
    new_preview.write_bytes(b"RIFF-new-preview")

    build_package(
        "New York voice",
        "en-US",
        reference,
        conditioning,
        preview,
        source,
        accent="new-york-city",
    )
    rebuild_package_for_engine(
        source,
        CURRENT_ENGINE,
        new_conditioning,
        new_preview,
        target,
    )

    manifest = validate_package(target)
    assert manifest["language"] == "en-US"
    assert manifest["accent"] == "new-york-city"
