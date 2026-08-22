from __future__ import annotations

import gc
import threading
from pathlib import Path

from voicerig.model_contract import (
    CHATTERBOX_MODEL,
    CHATTERBOX_SOURCE_REVISION,
    ROST_DANISH_MODEL,
    ROST_DANISH_REPO_ID,
    ROST_DANISH_REVISION,
    tts_defaults,
)
from voicerig.runtime import chatterbox_device


class ChatterboxUnavailable(RuntimeError):
    pass


# Keep at most one large Chatterbox-family checkpoint resident per device. The
# physical RTX 3060 target has 12 GB VRAM; caching both general V3 and Danish
# Røst simultaneously would make an A/B quality test needlessly OOM-prone.
# Value: ((model_name, revision), model_object)
_MODELS: dict[str, tuple[tuple[str, str], object]] = {}
_MODEL_LOAD_LOCK = threading.Lock()
# RLock lets a higher-level voice-build transaction hold the GPU state stable
# while the existing helpers keep their own defensive lock acquisition.
_MODEL_RUN_LOCK = threading.RLock()
# Identity of the conditionals currently resident in the shared mutable model.
# Package runtime and profile creation both mutate the same `model.conds`, so
# the cache key must live beside that state rather than in either caller.
_CONDITIONING_KEY: tuple[str, ...] | None = None


def _conditioning_key() -> tuple[str, ...] | None:
    return _CONDITIONING_KEY


def _set_conditioning_key(value: tuple[str, ...] | None) -> None:
    global _CONDITIONING_KEY
    _CONDITIONING_KEY = value


def _release_device_model(device: str) -> None:
    previous = _MODELS.pop(device, None)
    if previous is None:
        return
    _set_conditioning_key(None)
    del previous
    gc.collect()
    try:
        import torch

        if device.startswith("cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        # Releasing a previous optional model is best-effort. The subsequent
        # load remains authoritative and will fail closed if memory is not free.
        pass


def _load_model(model_name: str, revision: str, device: str):
    try:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS
    except Exception as exc:  # pragma: no cover - optional heavyweight dependency
        raise ChatterboxUnavailable(
            "Chatterbox er ikke installeret. Kør: pip install -e '.[voice]'"
        ) from exc

    try:
        if model_name == CHATTERBOX_MODEL and revision == CHATTERBOX_SOURCE_REVISION:
            return ChatterboxMultilingualTTS.from_pretrained(
                device=device,
                t3_model=CHATTERBOX_MODEL,
            )
        if model_name == ROST_DANISH_MODEL and revision == ROST_DANISH_REVISION:
            from huggingface_hub import snapshot_download

            model_dir = snapshot_download(
                repo_id=ROST_DANISH_REPO_ID,
                revision=ROST_DANISH_REVISION,
                allow_patterns=["*.safetensors", "*.json", "*.txt", "*.pt", "*.model"],
            )
            return ChatterboxMultilingualTTS.from_local(model_dir, device=device)
    except Exception as exc:  # pragma: no cover - model/runtime/network specific
        raise ChatterboxUnavailable(
            f"Chatterbox-modellen {model_name} kunne ikke indlæses på {device}."
        ) from exc

    raise ChatterboxUnavailable(
        f"Ukendt eller ikke-pinnet Chatterbox-model: {model_name}@{revision}."
    )


def _shared_model(
    model_name: str = CHATTERBOX_MODEL,
    revision: str = CHATTERBOX_SOURCE_REVISION,
):
    device = chatterbox_device()
    key = (model_name, revision)
    with _MODEL_LOAD_LOCK:
        resident = _MODELS.get(device)
        if resident is not None and resident[0] == key:
            return resident[1]
        if resident is not None:
            _release_device_model(device)
        model = _load_model(model_name, revision, device)
        _MODELS[device] = (key, model)
        _set_conditioning_key(None)
        return model


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
        defaults = tts_defaults(self.language)
        with _MODEL_RUN_LOCK:
            model.prepare_conditionals(str(reference_wav), exaggeration=defaults["exaggeration"])
            if model.conds is None:
                raise RuntimeError("Chatterbox oprettede ingen voice conditioning.")
            # This is a transient build identity, deliberately distinct from any
            # installed package key. Package runtime must reload after a build.
            _set_conditioning_key(("build", str(reference_wav.resolve())))
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
        defaults = tts_defaults(self.language)
        with _MODEL_RUN_LOCK:
            if model.conds is None:
                raise RuntimeError("Preview kræver forberedt voice conditioning.")
            wav = model.generate(
                text,
                language_id=self.language,
                exaggeration=defaults["exaggeration"],
                cfg_weight=defaults["cfg_weight"],
                temperature=defaults["temperature"],
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
