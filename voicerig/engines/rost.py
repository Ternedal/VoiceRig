from __future__ import annotations

from pathlib import Path

from voicerig.engines.chatterbox import (
    ChatterboxUnavailable,
    _MODEL_RUN_LOCK,
    _save_pcm16,
    _set_conditioning_key,
    _shared_model,
)
from voicerig.model_contract import (
    DEFAULT_TTS_EXAGGERATION,
    ROST_DANISH_CFG_WEIGHT,
    ROST_DANISH_MIN_P,
    ROST_DANISH_MODEL,
    ROST_DANISH_REPETITION_PENALTY,
    ROST_DANISH_REVISION,
    ROST_DANISH_TEMPERATURE,
    ROST_DANISH_TOP_P,
)


ROST_DANISH_TEST_TEXT = (
    "Hej, jeg taler dansk. Jeg vil gerne høre, om stemmen udtaler æ, ø og å naturligt. "
    "Rødgrød med fløde, København, højre, høre, gøre og selvfølgelig."
)


def synthesize_rost_danish(reference_wav: Path, text: str, output: Path) -> dict:
    """Generate a pinned Røst v3 Danish A/B sample from one VoiceRig reference.

    This intentionally does not alter the .mrvoice package or ModelRig default.
    It exists to physically compare the current general Chatterbox V3 runtime
    against a Danish-finetuned checkpoint before VoiceRig changes its package
    contract or default engine.
    """
    clean_text = str(text or "").strip()
    if not clean_text:
        raise ValueError("Skriv en dansk testtekst først.")
    if len(clean_text) > 4000:
        raise ValueError("Testteksten er for lang.")
    if not reference_wav.is_file():
        raise ValueError("Stemmeprofilens reference.wav mangler.")

    try:
        import torchaudio as ta
    except Exception as exc:  # pragma: no cover - heavyweight optional dependency
        raise ChatterboxUnavailable("torchaudio mangler i Chatterbox-installationen.") from exc

    model = _shared_model(ROST_DANISH_MODEL, ROST_DANISH_REVISION)
    with _MODEL_RUN_LOCK:
        model.prepare_conditionals(
            str(reference_wav),
            exaggeration=DEFAULT_TTS_EXAGGERATION,
        )
        if model.conds is None:
            raise RuntimeError("Røst kunne ikke oprette voice conditioning fra reference.wav.")
        _set_conditioning_key(("rost-compare", str(reference_wav.resolve())))
        wav = model.generate(
            clean_text,
            language_id="da",
            exaggeration=DEFAULT_TTS_EXAGGERATION,
            cfg_weight=ROST_DANISH_CFG_WEIGHT,
            temperature=ROST_DANISH_TEMPERATURE,
            repetition_penalty=ROST_DANISH_REPETITION_PENALTY,
            min_p=ROST_DANISH_MIN_P,
            top_p=ROST_DANISH_TOP_P,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        _save_pcm16(ta, output, wav, int(model.sr))

    frames = int(wav.shape[-1])
    sample_rate = int(model.sr)
    return {
        "engine": "Røst v3 Chatterbox 500M",
        "model": ROST_DANISH_MODEL,
        "revision": ROST_DANISH_REVISION,
        "sample_rate": sample_rate,
        "duration": round(frames / sample_rate, 3) if sample_rate else 0.0,
        "language": "da",
    }
