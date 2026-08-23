from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from voicerig.model_contract import (
    CHATTERBOX_ENGINE,
    CHATTERBOX_MODEL,
    CHATTERBOX_SOURCE_REVISION,
    OMNIVOICE_ASR_MODEL,
    OMNIVOICE_ASR_REVISION,
    OMNIVOICE_ENGINE,
    OMNIVOICE_MODEL,
    OMNIVOICE_MODEL_REVISION,
    OMNIVOICE_PACKAGE_VERSION,
    OMNIVOICE_SOURCE_REVISION,
    OMNIVOICE_TORCH_VERSION,
    OMNIVOICE_TORCHAUDIO_VERSION,
    ROST_DANISH_CFG_WEIGHT,
    ROST_DANISH_MIN_P,
    ROST_DANISH_REPETITION_PENALTY,
    ROST_DANISH_REPO_ID,
    ROST_DANISH_REVISION,
    ROST_DANISH_TEMPERATURE,
    ROST_DANISH_TOP_P,
)
from voicerig.source_control import current_source_status

SCHEMA_VERSION = 1
WINNERS = ("chatterbox", "rost", "omnivoice", "none")
CANDIDATE_KEYS = ("chatterbox", "rost", "omnivoice")


def candidate_contracts() -> dict[str, dict]:
    """Return the exact immutable identities used by the Danish A/B/C gate."""
    return {
        "chatterbox": {
            "label": "Chatterbox Multilingual V3",
            "engine": CHATTERBOX_ENGINE,
            "model": CHATTERBOX_MODEL,
            "source_revision": CHATTERBOX_SOURCE_REVISION,
            "language": "da",
        },
        "rost": {
            "label": "Røst v3 Chatterbox 500M",
            "engine": CHATTERBOX_ENGINE,
            "model": ROST_DANISH_REPO_ID,
            "source_revision": CHATTERBOX_SOURCE_REVISION,
            "model_revision": ROST_DANISH_REVISION,
            "language": "da",
            "generation": {
                "temperature": ROST_DANISH_TEMPERATURE,
                "cfg_weight": ROST_DANISH_CFG_WEIGHT,
                "top_p": ROST_DANISH_TOP_P,
                "min_p": ROST_DANISH_MIN_P,
                "repetition_penalty": ROST_DANISH_REPETITION_PENALTY,
            },
        },
        "omnivoice": {
            "label": "OmniVoice",
            "engine": OMNIVOICE_ENGINE,
            "model": OMNIVOICE_MODEL,
            "source_revision": OMNIVOICE_SOURCE_REVISION,
            "package_version": OMNIVOICE_PACKAGE_VERSION,
            "model_revision": OMNIVOICE_MODEL_REVISION,
            "language": "da",
            "asr_model": OMNIVOICE_ASR_MODEL,
            "asr_revision": OMNIVOICE_ASR_REVISION,
            "torch": OMNIVOICE_TORCH_VERSION,
            "torchaudio": OMNIVOICE_TORCHAUDIO_VERSION,
        },
    }


def _text_evidence(text: str) -> dict:
    encoded = text.encode("utf-8")
    return {
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "characters": len(text),
        "utf8_bytes": len(encoded),
    }


def _clean_score(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
        raise ValueError(f"{label} skal være et heltal fra 1 til 5.")
    return value


def _clean_note(value: object, label: str, *, required: bool = False) -> str | None:
    note = str(value or "").strip()
    if required and not note:
        raise ValueError(f"{label} må ikke være tom.")
    if len(note) > 1200:
        raise ValueError(f"{label} er for lang.")
    return note or None


def build_decision_report(
    *,
    winner: str,
    scores: Mapping[str, int],
    decision_note: str,
    candidate_notes: Mapping[str, str] | None = None,
    test_texts: list[str] | tuple[str, ...],
    source: Mapping | None = None,
) -> dict:
    winner = str(winner or "").strip().lower()
    if winner not in WINNERS:
        raise ValueError("winner skal være chatterbox, rost, omnivoice eller none.")

    source_data = dict(source or current_source_status())
    if source_data.get("available") is not True or not source_data.get("revision"):
        raise ValueError("Git HEAD kunne ikke aflæses; motorbeslutningen kræver et Git-checkout.")
    if source_data.get("dirty") is not False:
        raise ValueError("Checkoutet er dirty; motorbeslutningen skal optages fra et clean checkout.")
    if not source_data.get("root"):
        raise ValueError("Checkout-root kunne ikke aflæses.")

    score_map = {key: _clean_score(scores.get(key), f"score for {key}") for key in CANDIDATE_KEYS}
    if winner != "none":
        winner_score = score_map[winner]
        other_scores = [score for key, score in score_map.items() if key != winner]
        if winner_score <= max(other_scores):
            raise ValueError(
                "En navngiven winner skal have en entydigt højere samlet score end de to andre; brug none ved uafgjort."
            )

    clean_decision_note = _clean_note(decision_note, "decision_note", required=True)
    notes = candidate_notes or {}
    clean_notes = {
        key: _clean_note(notes.get(key), f"note for {key}")
        for key in CANDIDATE_KEYS
    }

    normalized_texts = [str(text).strip() for text in test_texts if str(text).strip()]
    if not normalized_texts:
        raise ValueError("Mindst én faktisk A/B/C-testtekst skal angives.")
    if len(normalized_texts) > 12:
        raise ValueError("Højst 12 testtekster kan registreres i én motorbeslutning.")

    return {
        "schema": SCHEMA_VERSION,
        "kind": "danish-engine-decision",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "source": source_data,
        "winner": winner,
        "scores": score_map,
        "decision_note": clean_decision_note,
        "candidate_notes": clean_notes,
        "test_inputs": [_text_evidence(text) for text in normalized_texts],
        "candidates": candidate_contracts(),
        "privacy": {
            "raw_audio_stored": False,
            "raw_text_stored": False,
            "profile_identity_stored": False,
        },
    }


def validate_decision_report(report: Mapping, *, expected_revision: str | None = None) -> dict:
    """Fail closed if a stored motor decision no longer matches the pinned contract."""
    if report.get("schema") != SCHEMA_VERSION or report.get("kind") != "danish-engine-decision":
        raise ValueError("Motorbeslutningsrapporten har ukendt schema/kind.")

    source = report.get("source")
    if not isinstance(source, Mapping) or source.get("available") is not True or source.get("dirty") is not False:
        raise ValueError("Motorbeslutningen er ikke bundet til et clean Git-checkout.")
    revision = source.get("revision")
    if not isinstance(revision, str) or not revision:
        raise ValueError("Motorbeslutningen mangler Git revision.")
    if expected_revision and revision != expected_revision:
        raise ValueError("Motorbeslutningens Git revision matcher ikke den forventede release-revision.")

    winner = str(report.get("winner") or "").lower()
    if winner not in WINNERS:
        raise ValueError("Motorbeslutningen har en ugyldig winner.")

    scores = report.get("scores")
    if not isinstance(scores, Mapping) or set(scores) != set(CANDIDATE_KEYS):
        raise ValueError("Motorbeslutningen skal indeholde score for alle tre kandidater.")
    clean_scores = {key: _clean_score(scores.get(key), f"score for {key}") for key in CANDIDATE_KEYS}
    if winner != "none" and clean_scores[winner] <= max(
        score for key, score in clean_scores.items() if key != winner
    ):
        raise ValueError("Motorbeslutningens winner er ikke entydigt højst scorende.")

    _clean_note(report.get("decision_note"), "decision_note", required=True)

    test_inputs = report.get("test_inputs")
    if not isinstance(test_inputs, list) or not test_inputs:
        raise ValueError("Motorbeslutningen mangler test-input evidence.")
    for item in test_inputs:
        if not isinstance(item, Mapping):
            raise ValueError("Ugyldigt test-input evidence.")
        digest = item.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64:
            raise ValueError("Test-input evidence mangler SHA-256.")
        if not isinstance(item.get("characters"), int) or item["characters"] <= 0:
            raise ValueError("Test-input evidence mangler tegnlængde.")
        if "text" in item or "raw" in item:
            raise ValueError("Motorbeslutningen må ikke gemme rå testtekst.")

    if report.get("candidates") != candidate_contracts():
        raise ValueError("Motorbeslutningens kandidatpins matcher ikke den aktuelle VoiceRig-kontrakt.")

    privacy = report.get("privacy")
    expected_privacy = {
        "raw_audio_stored": False,
        "raw_text_stored": False,
        "profile_identity_stored": False,
    }
    if privacy != expected_privacy:
        raise ValueError("Motorbeslutningens privacy-kontrakt er ugyldig.")

    return dict(report)


def main() -> int:
    parser = argparse.ArgumentParser(description="Record privacy-safe Danish VoiceRig A/B/C engine evidence")
    parser.add_argument("--winner", choices=WINNERS, required=True)
    parser.add_argument("--chatterbox-score", type=int, required=True)
    parser.add_argument("--rost-score", type=int, required=True)
    parser.add_argument("--omnivoice-score", type=int, required=True)
    parser.add_argument("--decision-note", required=True)
    parser.add_argument("--chatterbox-note", default="")
    parser.add_argument("--rost-note", default="")
    parser.add_argument("--omnivoice-note", default="")
    parser.add_argument("--test-text", action="append", default=[])
    parser.add_argument("--output", default="engine-decision.json")
    args = parser.parse_args()

    try:
        report = build_decision_report(
            winner=args.winner,
            scores={
                "chatterbox": args.chatterbox_score,
                "rost": args.rost_score,
                "omnivoice": args.omnivoice_score,
            },
            decision_note=args.decision_note,
            candidate_notes={
                "chatterbox": args.chatterbox_note,
                "rost": args.rost_note,
                "omnivoice": args.omnivoice_note,
            },
            test_texts=args.test_text,
        )
        validate_decision_report(report, expected_revision=report["source"]["revision"])
    except ValueError as exc:
        print(f"VoiceRig engine decision: FAIL: {exc}")
        return 1

    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"VoiceRig engine decision: PASS ({report['winner']})")
    print(f"Report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
