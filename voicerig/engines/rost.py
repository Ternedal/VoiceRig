from __future__ import annotations

from pathlib import Path

from voicerig.engines.catalog import ROST_DANISH_ENGINE_SPEC, defaults_for_engine
from voicerig.engines.chatterbox import (
    ChatterboxUnavailable,
    _MODEL_RUN_LOCK,
    _save_pcm16,
    _set_conditioning_key,
    _shared_model,
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

    spec = ROST_DANISH_ENGINE_SPEC
    shared = defaults_for_engine(spec, "da")
    options = dict(spec.option_defaults)

    # Model selection and generation share one lock. Switching from the current
    # general V3 checkpoint to Røst evicts the old GPU model, so no concurrent
    # package synthesis may keep using that object while it is being replaced.
    with _MODEL_RUN_LOCK:
        model = _shared_model(spec.model, spec.revision)
        model.prepare_conditionals(
            str(reference_wav),
            exaggeration=shared["exaggeration"],
        )
        if model.conds is None:
            raise RuntimeError("Røst kunne ikke oprette voice conditioning fra reference.wav.")
        _set_conditioning_key(("rost-compare", str(reference_wav.resolve())))
        wav = model.generate(
            clean_text,
            language_id="da",
            exaggeration=shared["exaggeration"],
            cfg_weight=shared["cfg_weight"],
            temperature=shared["temperature"],
            repetition_penalty=options["repetition_penalty"],
            min_p=options["min_p"],
            top_p=options["top_p"],
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        _save_pcm16(ta, output, wav, int(model.sr))

    frames = int(wav.shape[-1])
    sample_rate = int(model.sr)
    return {
        "engine": spec.label,
        "model": spec.model,
        "revision": spec.revision,
        "sample_rate": sample_rate,
        "duration": round(frames / sample_rate, 3) if sample_rate else 0.0,
        "language": "da",
    }
