from __future__ import annotations

import json

import pytest

from voicerig.engine_decision import (
    build_decision_report,
    candidate_contracts,
    validate_decision_report,
)
from voicerig.model_contract import (
    CHATTERBOX_SOURCE_REVISION,
    OMNIVOICE_MODEL_REVISION,
    OMNIVOICE_SOURCE_REVISION,
    ROST_DANISH_REVISION,
)


def _source(*, dirty: bool = False, revision: str = "a" * 40) -> dict:
    return {
        "available": True,
        "revision": revision,
        "branch": "release/voicerig-v1-physical-rc-test",
        "dirty": dirty,
        "root": "C:/VoiceRig",
    }


def _report(**overrides):
    values = {
        "winner": "rost",
        "scores": {"chatterbox": 2, "rost": 5, "omnivoice": 4},
        "decision_note": "Røst er klart mest naturlig på dansk og siger hele teksten.",
        "candidate_notes": {
            "chatterbox": "Svensk klang.",
            "rost": "Naturlig dansk.",
            "omnivoice": "God, men enkelte gentagelser.",
        },
        "test_texts": [
            "Hej, jeg taler dansk. Rødgrød med fløde.",
            "København, høre, gøre og selvfølgelig.",
        ],
        "source": _source(),
    }
    values.update(overrides)
    return build_decision_report(**values)


def test_engine_decision_records_exact_candidate_pins_without_raw_text_or_profile_identity():
    report = _report()
    contracts = report["candidates"]

    assert contracts["chatterbox"]["source_revision"] == CHATTERBOX_SOURCE_REVISION
    assert contracts["rost"]["model_revision"] == ROST_DANISH_REVISION
    assert contracts["omnivoice"]["source_revision"] == OMNIVOICE_SOURCE_REVISION
    assert contracts["omnivoice"]["model_revision"] == OMNIVOICE_MODEL_REVISION
    assert report["privacy"] == {
        "raw_audio_stored": False,
        "raw_text_stored": False,
        "profile_identity_stored": False,
    }

    serialized = json.dumps(report, ensure_ascii=False)
    assert "Rødgrød med fløde" not in serialized
    assert "København, høre, gøre" not in serialized
    assert len(report["test_inputs"]) == 2
    assert all(len(item["sha256"]) == 64 for item in report["test_inputs"])


def test_engine_decision_requires_clean_checkout_and_all_three_scores():
    with pytest.raises(ValueError, match="dirty"):
        _report(source=_source(dirty=True))

    with pytest.raises(ValueError, match="score for omnivoice"):
        _report(scores={"chatterbox": 2, "rost": 5})


def test_named_winner_must_be_strictly_highest_scoring():
    with pytest.raises(ValueError, match="entydigt højere"):
        _report(scores={"chatterbox": 3, "rost": 4, "omnivoice": 4})

    tied = _report(
        winner="none",
        scores={"chatterbox": 2, "rost": 4, "omnivoice": 4},
        decision_note="Ingen klar vinder; Røst og OmniVoice skal undersøges videre.",
    )
    assert tied["winner"] == "none"


def test_validate_decision_report_rejects_stale_release_revision_and_tampered_candidate_pin():
    report = _report()

    with pytest.raises(ValueError, match="release-revision"):
        validate_decision_report(report, expected_revision="b" * 40)

    report["candidates"]["omnivoice"]["model_revision"] = "0" * 40
    with pytest.raises(ValueError, match="kandidatpins"):
        validate_decision_report(report, expected_revision="a" * 40)


def test_validate_decision_report_rejects_raw_text_smuggling():
    report = _report()
    report["test_inputs"][0]["text"] = "rå tekst må ikke gemmes"

    with pytest.raises(ValueError, match="rå testtekst"):
        validate_decision_report(report, expected_revision="a" * 40)


def test_candidate_contract_function_returns_fresh_nested_data():
    first = candidate_contracts()
    first["rost"]["generation"]["top_p"] = 0.1
    second = candidate_contracts()

    assert second["rost"]["generation"]["top_p"] != 0.1
