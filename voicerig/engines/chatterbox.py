from __future__ import annotations

import threading
from pathlib import Path

from voicerig.runtime import chatterbox_device


class ChatterboxUnavailable(RuntimeError):
    pass


_MODELS: dict[str, object] = {}
_MODEL_LOAD_LOCK = threading.Lock()
# RLock lets a higher-level voice-build transaction hold the GPU state stable
# while the existing helpers keep their own defensive lock acquisition.
_MODEL_RUN_LOCK = threading.RLock()


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
        """Generate preview from the conditionals prepared immediately before it.

        `reference_wav` remains in the signature to keep the engine call stable,
        but passing it to Chatterbox.generate would call prepare_conditionals a
        second time. The normal build contract is build_conditioning -> preview.
        """
        del reference_wav
        try:
            import torchaudio as ta
        except Exception as exc:  # pragma: no cover
            raise ChatterboxUnavailable("torchaudio mangler i Chatterbox-installationen.") from exc
        model = _shared_model()
        text = "Hej. Dette er en prøve på den nye stemme i ModelRig."
        with _MODEL_RUN_LOCK:
            if model.conds is None:
                raise RuntimeError("Preview kræver forberedt voice conditioning.")
            wav = model.generate(
                text,
                language_id=self.language,
                exaggeration=0.5,
                cfg_weight=0.5,
                temperature=0.8,
            )
            output.parent.mkdir(parents=True, exist_ok=True)
            _save_pcm16(ta, output, wav, model.sr)
        return output

    def build_artifacts(self, reference_wav: Path, conditioning: Path, preview: Path) -> tuple[Path, Path]:
        """Create conditioning + preview as one atomic mutable-model transaction."""
        with _MODEL_RUN_LOCK:
            self.build_conditioning(reference_wav, conditioning)
            self.preview(reference_wav, preview)
        return conditioning, preview
