from __future__ import annotations

import hashlib
import json
import re
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path


FORMAT = "modelrig-voice"
FORMAT_VERSION = 1
_REQUIRED_PAYLOADS = {"reference.wav", "conditioning.pt", "preview.wav"}
_ALLOWED_TOP_LEVEL = {"manifest.json", "checksums.json", *_REQUIRED_PAYLOADS}


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


def build_package(name: str, language: str, reference: Path, conditioning: Path, preview: Path, output: Path, alternatives: list[Path] | None = None) -> Path:
    alternatives = alternatives or []
    voice_id = f"{slugify(name)}-{uuid.uuid4().hex[:8]}"
    manifest = Manifest(
        format=FORMAT,
        format_version=FORMAT_VERSION,
        id=voice_id,
        name=name.strip(),
        language=language,
        engine={"name": "chatterbox-multilingual", "model": "v3"},
        files={"reference": "reference.wav", "conditioning": "conditioning.pt", "preview": "preview.wav"},
        defaults={"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8},
    )
    files: list[tuple[Path, str]] = [(reference, "reference.wav"), (conditioning, "conditioning.pt"), (preview, "preview.wav")]
    for idx, alt in enumerate(alternatives[:5], start=1):
        files.append((alt, f"references/candidate_{idx:02d}.wav"))
    checksums = {arc: sha256(src) for src, arc in files}
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(asdict(manifest), ensure_ascii=False, indent=2))
        zf.writestr("checksums.json", json.dumps(checksums, indent=2))
        for src, arc in files:
            zf.write(src, arc)
    validate_package(output)
    return output


def validate_package(package: Path) -> dict:
    with zipfile.ZipFile(package, "r") as zf:
        infos = zf.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("Dublerede filer i .mrvoice-pakken.")
        for name in names:
            path = Path(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ValueError("Ugyldig sti i .mrvoice-pakken.")
            if name not in _ALLOWED_TOP_LEVEL and not name.startswith("references/"):
                raise ValueError(f"Ukendt fil i .mrvoice-pakken: {name}")
        required = {"manifest.json", "checksums.json", *_REQUIRED_PAYLOADS}
        missing = required.difference(names)
        if missing:
            raise ValueError(f"Manglende filer i .mrvoice: {sorted(missing)}")
        manifest = json.loads(zf.read("manifest.json"))
        if manifest.get("format") != FORMAT or manifest.get("format_version") != FORMAT_VERSION:
            raise ValueError("Ikke-understøttet .mrvoice-format.")
        expected_map = {"reference": "reference.wav", "conditioning": "conditioning.pt", "preview": "preview.wav"}
        if (manifest.get("files") or {}) != expected_map:
            raise ValueError("Manifestets filreferencer matcher ikke .mrvoice v1-kontrakten.")
        checksums = json.loads(zf.read("checksums.json"))
        payloads = {name for name in names if name not in {"manifest.json", "checksums.json"}}
        if set(checksums) != payloads:
            raise ValueError("Checksums dækker ikke præcis alle payload-filer.")
        for name, expected in checksums.items():
            actual = hashlib.sha256(zf.read(name)).hexdigest()
            if actual != expected:
                raise ValueError(f"Checksum-fejl i {name}")
        return manifest
