from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping

from voicerig.model_contract import (
    CHATTERBOX_ENGINE,
    CHATTERBOX_MODEL,
    CHATTERBOX_SOURCE_REVISION,
    ROST_DANISH_CFG_WEIGHT,
    ROST_DANISH_ENGINE,
    ROST_DANISH_MIN_P,
    ROST_DANISH_MODEL,
    ROST_DANISH_REPETITION_PENALTY,
    ROST_DANISH_REVISION,
    ROST_DANISH_TEMPERATURE,
    ROST_DANISH_TOP_P,
    DEFAULT_TTS_EXAGGERATION,
    tts_defaults,
)


@dataclass(frozen=True)
class NumericOption:
    minimum: float
    maximum: float


@dataclass(frozen=True)
class EngineSpec:
    name: str
    model: str
    revision: str
    label: str
    option_defaults: Mapping[str, float]
    option_ranges: Mapping[str, NumericOption]

    @property
    def identity(self) -> tuple[str, str, str]:
        return (self.name, self.model, self.revision)


CURRENT_ENGINE = EngineSpec(
    name=CHATTERBOX_ENGINE,
    model=CHATTERBOX_MODEL,
    revision=CHATTERBOX_SOURCE_REVISION,
    label="Chatterbox Multilingual V3",
    option_defaults={},
    option_ranges={},
)

ROST_DANISH_ENGINE_SPEC = EngineSpec(
    name=ROST_DANISH_ENGINE,
    model=ROST_DANISH_MODEL,
    revision=ROST_DANISH_REVISION,
    label="Røst v3 Chatterbox 500M",
    option_defaults={
        "repetition_penalty": ROST_DANISH_REPETITION_PENALTY,
        "min_p": ROST_DANISH_MIN_P,
        "top_p": ROST_DANISH_TOP_P,
    },
    option_ranges={
        "repetition_penalty": NumericOption(1.0, 10.0),
        "min_p": NumericOption(0.0, 1.0),
        "top_p": NumericOption(0.0, 1.0),
    },
)

KNOWN_ENGINES = (CURRENT_ENGINE, ROST_DANISH_ENGINE_SPEC)
RUNTIME_ENGINES = (CURRENT_ENGINE, ROST_DANISH_ENGINE_SPEC)


def _identity(engine: Mapping | None) -> tuple[str, str, str | None]:
    value = engine or {}
    return (
        str(value.get("name") or ""),
        str(value.get("model") or ""),
        str(value.get("revision")) if value.get("revision") is not None else None,
    )


def exact_engine_spec(engine: Mapping | None) -> EngineSpec | None:
    identity = _identity(engine)
    for spec in KNOWN_ENGINES:
        if identity == spec.identity:
            return spec
    return None


def runtime_engine_spec(manifest: Mapping) -> EngineSpec | None:
    """Resolve the exact model VoiceRig may execute for one validated package.

    Exact pinned current and Røst packages are runtime-supported. Historical
    current-Chatterbox packages with the same engine/model remain portable by
    rebuilding conditioning from reference.wav on the current source revision.
    Unknown engines never fall back silently.
    """
    engine = manifest.get("engine") if isinstance(manifest, Mapping) else None
    mapping = engine if isinstance(engine, Mapping) else None
    known = exact_engine_spec(mapping)
    if known is not None and any(known.identity == spec.identity for spec in RUNTIME_ENGINES):
        return known

    identity = _identity(mapping)
    if identity[0] == CURRENT_ENGINE.name and identity[1] == CURRENT_ENGINE.model:
        return CURRENT_ENGINE
    return None


def validate_engine_options(engine: Mapping) -> dict[str, float]:
    """Validate optional engine-specific generation controls.

    Legacy/current v1 manifests do not need an ``options`` key. If a package
    opts into engine-specific options, the engine revision must be one of the
    exact pinned specs and the option set must be complete. That keeps a voice
    package reproducible instead of depending on hidden runtime defaults.
    """
    if "options" not in engine:
        return {}
    raw = engine.get("options")
    if not isinstance(raw, dict):
        raise ValueError("Manifestets engine.options skal være et objekt.")

    spec = exact_engine_spec(engine)
    if spec is None:
        raise ValueError("engine.options kræver en kendt og eksakt pinnet engine-revision.")

    expected = set(spec.option_defaults)
    if set(raw) != expected:
        raise ValueError(
            f"Manifestets engine.options matcher ikke kontrakten for {spec.label}."
        )

    clean: dict[str, float] = {}
    for name, bounds in spec.option_ranges.items():
        value = raw.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"Engine-option {name} skal være et tal.")
        number = float(value)
        if not math.isfinite(number) or not bounds.minimum <= number <= bounds.maximum:
            raise ValueError(f"Engine-option {name} ligger uden for det tilladte interval.")
        clean[name] = number
    return clean


def manifest_engine(spec: EngineSpec = CURRENT_ENGINE, *, include_options: bool = False) -> dict:
    result = {
        "name": spec.name,
        "model": spec.model,
        "revision": spec.revision,
    }
    if include_options:
        result["options"] = dict(spec.option_defaults)
        validate_engine_options(result)
    return result


def defaults_for_engine(spec: EngineSpec, language: str) -> dict[str, float]:
    if spec.identity == ROST_DANISH_ENGINE_SPEC.identity:
        return {
            "exaggeration": DEFAULT_TTS_EXAGGERATION,
            "cfg_weight": ROST_DANISH_CFG_WEIGHT,
            "temperature": ROST_DANISH_TEMPERATURE,
        }
    return tts_defaults(language)


def package_compatibility(manifest: Mapping) -> dict:
    """Describe runtime compatibility without mutating or migrating a profile."""
    engine = manifest.get("engine") if isinstance(manifest, Mapping) else None
    mapping = engine if isinstance(engine, Mapping) else None
    identity = _identity(mapping)

    exact = exact_engine_spec(mapping)
    if exact is not None and runtime_engine_spec(manifest) is not None:
        return {
            "state": "direct",
            "runtime_supported": True,
            "can_rebuild_from_reference": True,
            "known_engine": True,
            "detail": f"Profilens engine og revision matcher den understøttede runtime: {exact.label}.",
        }

    if identity[0] == CURRENT_ENGINE.name and identity[1] == CURRENT_ENGINE.model:
        return {
            "state": "runtime-rebuild",
            "runtime_supported": True,
            "can_rebuild_from_reference": True,
            "known_engine": True,
            "detail": "Conditioning skal regenereres fra reference.wav for den aktive Chatterbox-revision.",
        }

    known = exact_engine_spec(mapping)
    if known is not None:
        return {
            "state": "reference-portable",
            "runtime_supported": False,
            "can_rebuild_from_reference": True,
            "known_engine": True,
            "detail": f"Profilens reference.wav kan genbruges med {known.label}, men motoren er ikke runtime-aktiv.",
        }

    return {
        "state": "unsupported",
        "runtime_supported": False,
        "can_rebuild_from_reference": False,
        "known_engine": False,
        "detail": "Engine/model er ukendt for denne VoiceRig-runtime.",
    }
