from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from voicerig.model_contract import (
    CHATTERBOX_ENGINE,
    CHATTERBOX_MODEL,
    CHATTERBOX_SOURCE_REVISION,
)

FORMAT = "modelrig-voice"
FORMAT_VERSION = 1
_REQUIRED_PAYLOADS = {"reference.wav", "conditioning.pt", "preview.wav"}
_ALLOWED_TOP_LEVEL = {"manifest.json", "checksums.json", *_REQUIRED_PAYLOADS}
_MAX_ENTRIES = 10
_MAX_TOTAL_UNCOMPRESSED = 128 * 1024 * 1024
_MAX_METADATA_BYTES = 256 * 1024
_MAX_WAV_BYTES = 16 * 1024 * 1024
_MAX_CONDITIONING_BYTES = 64 * 1024 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_LANGUAGE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")
_VOICE_ID = re.compile(r"^[a-z0-9æøå_-]{1,160}$")
_REFERENCE_PAYLOAD = re.compile(r"^references/candidate_0[1-5]\.wav$")


@dataclass(frozen=True)
class Manifest:
    format: str
    format_version: int
    id: str
    name: str
    language: str
    engine: dict
    files: dict
    defaults: dict


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9æøå_-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "voice"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def build_package(
    name: str,
    language: str,
    reference: Path,
    conditioning: Path,
    preview: Path,
    output: Path,
    alternatives: list[Path] | None = None,
) -> Path:
    alternatives = alternatives or []
    voice_id = f"{slugify(name)}-{uuid.uuid4().hex[:8]}"
    manifest = Manifest(
        format=FORMAT,
        format_version=FORMAT_VERSION,
        id=voice_id,
        name=name.strip(),
        language=language,
        engine={
            "name": CHATTERBOX_ENGINE,
            "model": CHATTERBOX_MODEL,
            "revision": CHATTERBOX_SOURCE_REVISION,
        },
        files={
            "reference": "reference.wav",
            "conditioning": "conditioning.pt",
            "preview": "preview.wav",
        },
        defaults={"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8},
    )
    files: list[tuple[Path, str]] = [
        (reference, "reference.wav"),
        (conditioning, "conditioning.pt"),
        (preview, "preview.wav"),
    ]
    for idx, alt in enumerate(alternatives[:5], start=1):
        files.append((alt, f"references/candidate_{idx:02d}.wav"))
    checksums = {arc: sha256(src) for src, arc in files}

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(output.name + ".tmp")
    temp.unlink(missing_ok=True)
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "manifest.json",
                json.dumps(asdict(manifest), ensure_ascii=False, indent=2),
            )
            zf.writestr("checksums.json", json.dumps(checksums, indent=2))
            for src, arc in files:
                zf.write(src, arc)
        validate_package(temp)
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return output


def _member_limit(name: str) -> int:
    if name in {"manifest.json", "checksums.json"}:
        return _MAX_METADATA_BYTES
    if name == "conditioning.pt":
        return _MAX_CONDITIONING_BYTES
    if name in {"reference.wav", "preview.wav"} or _REFERENCE_PAYLOAD.fullmatch(name):
        return _MAX_WAV_BYTES
    return 0


def _validate_archive_shape(infos: list[zipfile.ZipInfo]) -> list[str]:
    if len(infos) > _MAX_ENTRIES:
        raise ValueError("For mange filer i .mrvoice-pakken.")
    names = [info.filename for info in infos]
    if len(names) != len(set(names)):
        raise ValueError("Dublerede filer i .mrvoice-pakken.")

    total = 0
    for info in infos:
        name = info.filename
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise ValueError("Ugyldig sti i .mrvoice-pakken.")
        if name not in _ALLOWED_TOP_LEVEL and not _REFERENCE_PAYLOAD.fullmatch(name):
            raise ValueError(f"Ukendt fil i .mrvoice-pakken: {name}")
        if info.flag_bits & 0x1:
            raise ValueError("Krypterede filer understøttes ikke i .mrvoice.")
        limit = _member_limit(name)
        if limit <= 0 or info.file_size > limit:
            raise ValueError(f"{name} er for stor til .mrvoice v1-kontrakten.")
        total += info.file_size
        if total > _MAX_TOTAL_UNCOMPRESSED:
            raise ValueError(".mrvoice-pakken er for stor efter udpakning.")
    return names


def _json_no_constants(value: str):
    raise ValueError(f"Ugyldig JSON-konstant i .mrvoice: {value}")


def _nonempty_string(value, field: str, max_len: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Manifestfeltet {field} skal være tekst.")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > max_len or any(ord(ch) < 32 for ch in cleaned):
        raise ValueError(f"Manifestfeltet {field} er ugyldigt.")
    return cleaned


def _bounded_number(defaults: dict, field: str, minimum: float, maximum: float) -> float:
    value = defaults.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"TTS-default {field} skal være et tal.")
    value = float(value)
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f"TTS-default {field} ligger uden for det tilladte interval.")
    return value


def _validate_manifest(manifest) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("manifest.json skal indeholde et JSON-objekt.")
    if manifest.get("format") != FORMAT or manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError("Ikke-understøttet .mrvoice-format.")

    voice_id = _nonempty_string(manifest.get("id"), "id", 160)
    if not _VOICE_ID.fullmatch(voice_id):
        raise ValueError(
            "Manifestets id er ugyldigt; brug kun lowercase bogstaver, tal, æøå, _ og -."
        )
    _nonempty_string(manifest.get("name"), "name", 160)
    language = _nonempty_string(manifest.get("language"), "language", 16)
    if not _LANGUAGE.fullmatch(language):
        raise ValueError("Manifestets language er ugyldigt.")

    engine = manifest.get("engine")
    if not isinstance(engine, dict):
        raise ValueError("Manifestets engine skal være et objekt.")
    _nonempty_string(engine.get("name"), "engine.name", 80)
    _nonempty_string(engine.get("model"), "engine.model", 80)
    revision = engine.get("revision")
    if revision is not None:
        revision = _nonempty_string(revision, "engine.revision", 64)
        if not _HEX40.fullmatch(revision):
            raise ValueError("Manifestets engine.revision er ugyldig.")

    expected_map = {
        "reference": "reference.wav",
        "conditioning": "conditioning.pt",
        "preview": "preview.wav",
    }
    if manifest.get("files") != expected_map:
        raise ValueError("Manifestets filreferencer matcher ikke .mrvoice v1-kontrakten.")

    defaults = manifest.get("defaults")
    if not isinstance(defaults, dict) or set(defaults) != {
        "exaggeration",
        "cfg_weight",
        "temperature",
    }:
        raise ValueError("Manifestets TTS-defaults matcher ikke .mrvoice v1-kontrakten.")
    _bounded_number(defaults, "exaggeration", 0.0, 2.0)
    _bounded_number(defaults, "cfg_weight", 0.0, 2.0)
    _bounded_number(defaults, "temperature", 0.05, 5.0)
    return manifest


def validate_package(package: Path) -> dict:
    with zipfile.ZipFile(package, "r") as zf:
        names = _validate_archive_shape(zf.infolist())
        required = {"manifest.json", "checksums.json", *_REQUIRED_PAYLOADS}
        missing = required.difference(names)
        if missing:
            raise ValueError(f"Manglende filer i .mrvoice: {sorted(missing)}")
        try:
            manifest = json.loads(
                zf.read("manifest.json"), parse_constant=_json_no_constants
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("manifest.json er ugyldig JSON.") from exc
        _validate_manifest(manifest)
        try:
            checksums = json.loads(
                zf.read("checksums.json"), parse_constant=_json_no_constants
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("checksums.json er ugyldig JSON.") from exc
        if not isinstance(checksums, dict):
            raise ValueError("checksums.json skal indeholde et JSON-objekt.")
        payloads = {
            name for name in names if name not in {"manifest.json", "checksums.json"}
        }
        if set(checksums) != payloads:
            raise ValueError("Checksums dækker ikke præcis alle payload-filer.")
        for name, expected in checksums.items():
            if not isinstance(expected, str) or not _HEX64.fullmatch(expected):
                raise ValueError(f"Ugyldig SHA-256 checksum for {name}")
            actual = hashlib.sha256(zf.read(name)).hexdigest()
            if actual != expected:
                raise ValueError(f"Checksum-fejl i {name}")
        return manifest
