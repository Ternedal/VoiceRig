from __future__ import annotations

import threading
from pathlib import Path

from voicerig.runtime import chatterbox_device


class ChatterboxUnavailable(RuntimeError):
    pass


_MODELS: dict[str, object] = {}
_MODEL_LOAD_LOCK = threading.Lock()
_MODEL_RUN_LOCK = threading.Lock()


def _shared_model():
    try:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    except Exception as exc:  # pragma: no cover - optional heavyweight dependency
        raise ChatterboxUnavailable(
            "Chatterbox er ikke installeret. Kør: pip install -e '.[voice]'"
        ) from exc

    device = chatterbox_device()
    with _MODEL_LOAD_LOCK:
        if device not in _MODELS:
            try:
                _MODELS[device] = ChatterboxMultilingualTTS.from_pretrained(
                    device=device,
                    t3_model="v3",
                )
            except Exception as exc:  # pragma: no cover - model/runtime specific
                raise ChatterboxUnavailable(
                    f"Chatterbox V3 kunne ikke indlæses på {device}."
                ) from exc
        return _MODELS[device]


def _save_pcm16(ta, path: Path, wav, sample_rate: int) -> None:
    """Keep .mrvoice/runtime WAVs deterministic across torchaudio backends."""
    ta.save(
        str(path),
        wav,
        sample_rate,
        format="wav",
        encoding="PCM_S",
        bits_per_sample=16,
    )


class ChatterboxEngine:
    def __init__(self, language: str = "da") -> None:
        self.language = language

    def build_conditioning(self, reference_wav: Path, output: Path) -> Path:
        model = _shared_model()
        with _MODEL_RUN_LOCK:
            model.prepare_conditionals(str(reference_wav), exaggeration=0.5)
            if model.conds is None:
                raise RuntimeError("Chatterbox oprettede ingen voice conditioning.")
            output.parent.mkdir(parents=True, exist_ok=True)
            model.conds.save(output)
        return output

    def preview(self, reference_wav: Path, output: Path) -> Path:
        try:
            import torchaudio as ta
        except Exception as exc:  # pragma: no cover
            raise ChatterboxUnavailable("torchaudio mangler i Chatterbox-installationen.") from exc
        model = _shared_model()
        text = "Hej. Dette er en prøve på den nye stemme i ModelRig."
        with _MODEL_RUN_LOCK:
            wav = model.generate(
                text,
                language_id=self.language,
                audio_prompt_path=str(reference_wav),
                exaggeration=0.5,
                cfg_weight=0.5,
                temperature=0.8,
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            _save_pcm16(ta, output, wav, model.sr)
        return output
