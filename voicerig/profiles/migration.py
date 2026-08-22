from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from voicerig.engines.catalog import EngineSpec, manifest_engine
from voicerig.profiles.package import build_package, validate_package


def migration_plan(package: Path, target_engine: EngineSpec) -> dict:
    """Return a non-mutating migration plan for a validated voice package."""
    manifest = validate_package(package)
    with zipfile.ZipFile(package, "r") as zf:
        alternatives = sorted(
            name
            for name in zf.namelist()
            if name.startswith("references/candidate_") and name.endswith(".wav")
        )
    return {
        "voice_id": manifest["id"],
        "name": manifest["name"],
        "language": manifest["language"],
        "source_engine": manifest.get("engine") or {},
        "target_engine": manifest_engine(
            target_engine,
            include_options=bool(target_engine.option_defaults),
        ),
        "preserves_voice_id": True,
        "preserves_reference": True,
        "backup_reference_count": len(alternatives),
        "requires_new_conditioning": True,
        "requires_new_preview": True,
    }


def rebuild_package_for_engine(
    source: Path,
    target_engine: EngineSpec,
    conditioning: Path,
    preview: Path,
    output: Path,
) -> Path:
    """Repackage one voice for a target engine using its authoritative audio.

    Engine-specific conditioning and preview must already have been generated
    by the caller. This helper deliberately does not synthesize or download a
    model. It validates the source, extracts only documented reference payloads
    to a private temporary directory, preserves the logical voice id, and uses
    build_package's validate-then-os.replace transaction for the output.

    ``output`` may equal ``source``: all authoritative audio is materialized
    before the atomic replacement begins.
    """
    manifest = validate_package(source)
    with tempfile.TemporaryDirectory(prefix="voicerig-engine-migration-") as tmp:
        root = Path(tmp)
        reference = root / "reference.wav"
        alternatives: list[Path] = []
        with zipfile.ZipFile(source, "r") as zf:
            reference.write_bytes(zf.read("reference.wav"))
            for idx in range(1, 6):
                name = f"references/candidate_{idx:02d}.wav"
                if name not in zf.namelist():
                    continue
                target = root / f"candidate_{idx:02d}.wav"
                target.write_bytes(zf.read(name))
                alternatives.append(target)

        return build_package(
            str(manifest["name"]),
            str(manifest["language"]),
            reference,
            conditioning,
            preview,
            output,
            alternatives=alternatives,
            engine_spec=target_engine,
            voice_id=str(manifest["id"]),
        )
