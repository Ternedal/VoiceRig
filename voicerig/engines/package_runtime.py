from __future__ import annotations

import importlib.util
import os
import threading
import zipfile
from pathlib import Path

from voicerig.config import data_dir
from voicerig.engines.chatterbox import _MODEL_RUN_LOCK, _shared_model
from voicerig.profiles.package import validate_package
from voicerig.runtime import chatterbox_device

_ACTIVE_LOCK = threading.Lock()
_ACTIVE_KEY: tuple[str, str] | None = None
_VALIDATION_LOCK = threading.Lock()
_VALIDATION_CACHE: dict[tuple[str, int, int], dict] = {}


def modelrig_voices_dir() -> Path:
    value = os.getenv("MODELRIG_VOICES_DIR", "~/.kaliv/voices")
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manifest(package: Path) -> dict:
    stat = package.stat()
    key = (str(package.resolve()), stat.st_mtime_ns, stat.st_size)
    with _VALIDATION_LOCK:
        cached = _VALIDATION_CACHE.get(key)
        if cached is not None:
            return cached
    manifest = validate_package(package)
    with _VALIDATION_LOCK:
        path_key = key[0]
        for old in [item for item in _VALIDATION_CACHE if item[0] == path_key and item != key]:
            _VALIDATION_CACHE.pop(old, None)
        _VALIDATION_CACHE[key] = manifest
    return manifest


def resolve_package(voice_package: str | None = None) -> Path:
    root = modelrig_voices_dir()
    if voice_package:
        safe = Path(voice_package).name
        if safe != voice_package or not safe.endswith(".mrvoice"):
            raise ValueError("Ugyldigt voice package-navn.")
        candidate = root / safe
        if not candidate.is_file():
            raise ValueError("Den valgte stemmeprofil findes ikke.")
        _manifest(candidate)
        return candidate

    marker = root / "default.txt"
    if marker.is_file():
        name = marker.read_text(encoding="utf-8").strip()
        if name and Path(name).name == name and name.endswith(".mrvoice"):
            candidate = root / name
            if candidate.is_file():
                _manifest(candidate)
                return candidate

    profiles = sorted(root.glob("*.mrvoice"))
    if len(profiles) == 1:
        _manifest(profiles[0])
        return profiles[0]
    if not profiles:
        raise ValueError("Ingen ModelRig-stemmeprofil er installeret.")
    raise ValueError("Flere stemmer er installeret, men ingen er valgt som default.")


def _materialize(package: Path, manifest: dict) -> Path:
    root = data_dir() / "tts-runtime" / str(manifest["id"])
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package, "r") as zf:
        for name in ("reference.wav", "conditioning.pt"):
            target = root / name
            raw = zf.read(name)
            if not target.exists() or target.read_bytes() != raw:
                temp = target.with_suffix(target.suffix + ".tmp")
                temp.write_bytes(raw)
                os.replace(temp, target)
    return root


def _ensure_conditioning(model, package: Path, manifest: dict, device: str) -> None:
    global _ACTIVE_KEY
    key = (str(manifest["id"]), device)
    with _ACTIVE_LOCK:
        if _ACTIVE_KEY == key and model.conds is not None:
            return
        cache = _materialize(package, manifest)
        try:
            from chatterbox.mtl_tts import Conditionals
            model.conds = Conditionals.load(
                cache / "conditioning.pt",
                map_location=device,
            ).to(device)
        except Exception:
            model.prepare_conditionals(str(cache / "reference.wav"), exaggeration=0.5)
            if model.conds is None:
                raise RuntimeError("Chatterbox kunne ikke oprette conditioning fra reference.wav")
        _ACTIVE_KEY = key


def synthesize(package: Path, text: str, output: Path) -> dict:
    manifest = _manifest(package)
    device = chatterbox_device()
    model = _shared_model()
    defaults = manifest.get("defaults") or {}

    with _MODEL_RUN_LOCK:
        _ensure_conditioning(model, package, manifest, device)
        wav = model.generate(
            text,
            language_id=manifest.get("language") or "da",
            exaggeration=float(defaults.get("exaggeration", 0.5)),
            cfg_weight=float(defaults.get("cfg_weight", 0.5)),
            temperature=float(defaults.get("temperature", 0.8)),
        )
        try:
            import torchaudio as ta
        except Exception as exc:
            raise RuntimeError("torchaudio mangler i VoiceRig-runtime.") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
        ta.save(str(output), wav, model.sr)
        frames = int(wav.shape[-1])
        duration = round(frames / int(model.sr), 3) if model.sr else 0.0
        return {
            "voice_id": manifest["id"],
            "voice": manifest["name"],
            "package": package.name,
            "sample_rate": int(model.sr),
            "duration": duration,
            "device": device,
        }


def status() -> dict:
    try:
        package = resolve_package()
        manifest = _manifest(package)
    except Exception as exc:
        return {"ok": False, "detail": str(exc), "voice": None, "package": None}

    try:
        chatterbox_installed = importlib.util.find_spec("chatterbox.mtl_tts") is not None
    except (ImportError, ModuleNotFoundError):
        chatterbox_installed = False
    if not chatterbox_installed:
        return {
            "ok": False,
            "detail": "chatterbox-tts er ikke installeret i VoiceRig-miljøet",
            "voice": manifest.get("name"),
            "package": package.name,
        }
    try:
        device = chatterbox_device()
    except RuntimeError as exc:
        return {
            "ok": False,
            "detail": str(exc),
            "voice": manifest.get("name"),
            "package": package.name,
        }
    return {
        "ok": True,
        "detail": None,
        "voice": manifest.get("name"),
        "voice_id": manifest.get("id"),
        "package": package.name,
        "device": device,
    }
