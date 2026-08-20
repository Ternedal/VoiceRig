from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from voicerig.config import data_dir
from voicerig.modelrig.client import install_local
from voicerig.profiles.package import slugify, validate_package


def library_dir() -> Path:
    path = data_dir() / "voices"
    path.mkdir(parents=True, exist_ok=True)
    return path


def modelrig_voices_dir() -> Path:
    value = os.getenv("MODELRIG_VOICES_DIR", "~/.kaliv/voices")
    path = Path(value).expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_package_name(filename: str) -> str:
    cleaned = str(filename or "").strip()
    if not cleaned or Path(cleaned).name != cleaned or not cleaned.lower().endswith(".mrvoice"):
        raise ValueError("Ugyldigt .mrvoice-filnavn.")
    return cleaned


def default_package_name() -> str | None:
    marker = modelrig_voices_dir() / "default.txt"
    if not marker.is_file():
        return None
    try:
        name = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not name or Path(name).name != name or not name.endswith(".mrvoice"):
        return None
    return name


def _package_paths() -> dict[str, dict[str, Path]]:
    found: dict[str, dict[str, Path]] = {}
    for source, root in (("library", library_dir()), ("modelrig", modelrig_voices_dir())):
        for package in root.glob("*.mrvoice"):
            if not package.is_file():
                continue
            found.setdefault(package.name, {})[source] = package
    return found


def find_package(filename: str) -> Path:
    safe = _safe_package_name(filename)
    local = library_dir() / safe
    if local.is_file():
        validate_package(local)
        return local
    installed = modelrig_voices_dir() / safe
    if installed.is_file():
        validate_package(installed)
        return installed
    raise FileNotFoundError("Stemmeprofilen findes ikke.")


def _voice_record(name: str, locations: dict[str, Path], default_name: str | None) -> dict:
    source = locations.get("library") or locations.get("modelrig")
    if source is None:
        raise ValueError("Stemmeprofilen har ingen gyldig placering.")
    manifest = validate_package(source)
    stat = source.stat()
    engine = manifest.get("engine") or {}
    return {
        "id": manifest["id"],
        "name": manifest["name"],
        "language": manifest["language"],
        "package": name,
        "is_default": name == default_name,
        "in_library": "library" in locations,
        "installed_in_modelrig": "modelrig" in locations,
        "size_bytes": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
        "engine": {
            "name": engine.get("name"),
            "model": engine.get("model"),
            "revision": engine.get("revision"),
        },
        "preview_url": f"/api/voices/{name}/preview",
        "download_url": f"/api/packages/{name}",
    }


def list_voices() -> dict:
    default_name = default_package_name()
    voices: list[dict] = []
    invalid: list[dict] = []
    for name, locations in sorted(_package_paths().items()):
        try:
            voices.append(_voice_record(name, locations, default_name))
        except Exception as exc:  # noqa: BLE001 - corrupt packages must remain visible to the UI
            invalid.append(
                {
                    "package": name,
                    "detail": str(exc),
                    "in_library": "library" in locations,
                    "installed_in_modelrig": "modelrig" in locations,
                }
            )
    voices.sort(key=lambda item: (not item["is_default"], str(item["name"]).casefold()))
    return {"voices": voices, "invalid": invalid, "default_package": default_name}


def preview_wav(filename: str) -> bytes:
    package = find_package(filename)
    validate_package(package)
    with zipfile.ZipFile(package, "r") as zf:
        return zf.read("preview.wav")


def import_package(source: Path, original_name: str | None = None) -> dict:
    manifest = validate_package(source)
    requested = Path(original_name or "").name
    if requested and requested == (original_name or "") and requested.lower().endswith(".mrvoice"):
        filename = requested
    else:
        filename = f"{slugify(manifest['name'])}.mrvoice"

    target = library_dir() / filename
    if target.exists():
        try:
            existing = validate_package(target)
        except Exception:
            existing = None
        if existing and existing.get("id") != manifest.get("id"):
            filename = f"{slugify(manifest['name'])}-{str(manifest['id'])[-8:]}.mrvoice"
            target = library_dir() / filename

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False, suffix=".mrvoice.tmp") as tmp:
        temp_path = Path(tmp.name)
    try:
        shutil.copy2(source, temp_path)
        validate_package(temp_path)
        os.replace(temp_path, target)
    finally:
        temp_path.unlink(missing_ok=True)

    return _voice_record(target.name, {"library": target}, default_package_name())


def set_default(filename: str) -> dict:
    package = find_package(filename)
    result = install_local(package)
    listing = list_voices()
    selected = next((voice for voice in listing["voices"] if voice["package"] == package.name), None)
    if selected is None:
        raise RuntimeError("Stemmen blev installeret, men kunne ikke genfindes i biblioteket.")
    return {"ok": True, "voice": selected, "install": result}


def delete_voice(filename: str) -> dict:
    safe = _safe_package_name(filename)
    roots = (library_dir(), modelrig_voices_dir())
    removed: list[str] = []
    for root in roots:
        package = root / safe
        if package.is_file():
            package.unlink()
            removed.append(str(package))

    marker = modelrig_voices_dir() / "default.txt"
    if default_package_name() == safe:
        marker.unlink(missing_ok=True)

    # Voice-build keeps a convenience copy of the selected reference next to
    # packages. It is not part of the portable profile and may be removed with
    # the corresponding local package.
    sidecar = library_dir() / f"{Path(safe).stem}-reference.wav"
    sidecar.unlink(missing_ok=True)

    if not removed:
        raise FileNotFoundError("Stemmeprofilen findes ikke.")
    return {"ok": True, "package": safe, "removed": removed}
