from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

from voicerig.engines.catalog import EngineSpec, manifest_engine
from voicerig.profiles.package import build_package, validate_package


def _reference_members(zf: zipfile.ZipFile) -> list[str]:
    names = set(zf.namelist())
    members = ["reference.wav"]
    members.extend(
        name
        for name in (f"references/candidate_{idx:02d}.wav" for idx in range(1, 6))
        if name in names
    )
    return members


def migration_plan(package: Path, target_engine: EngineSpec) -> dict:
    """Return a non-mutating migration plan for a validated voice package."""
    manifest = validate_package(package)
    with zipfile.ZipFile(package, "r") as zf:
        members = _reference_members(zf)
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
        "reference_count": len(members),
        "backup_reference_count": max(0, len(members) - 1),
        "requires_new_conditioning": True,
        "requires_new_preview": True,
    }


def rebuild_package_for_engine(
    source: Path,
    target_engine: EngineSpec,
    conditioning: Path,
    preview: Path,
    output: Path,
    *,
    reference_index: int = 0,
) -> Path:
    """Repackage one voice for a target engine using one stored reference.

    Engine-specific conditioning and preview must already have been generated
    from the same ``reference_index`` by the caller. The selected stored
    reference becomes authoritative ``reference.wav`` in the rebuilt package;
    every other stored reference remains available as a backup candidate.

    ``output`` may equal ``source``. All authoritative audio is materialized in
    a private temporary directory before build_package performs its validated
    atomic replacement, so a failure cannot partially mutate the source.
    """
    manifest = validate_package(source)
    with tempfile.TemporaryDirectory(prefix="voicerig-engine-migration-") as tmp:
        root = Path(tmp)
        alternatives: list[Path] = []
        with zipfile.ZipFile(source, "r") as zf:
            members = _reference_members(zf)
            if reference_index < 0 or reference_index >= len(members):
                raise ValueError("Den valgte reference findes ikke længere i stemmeprofilen.")

            selected_name = members[reference_index]
            reference = root / "reference.wav"
            reference.write_bytes(zf.read(selected_name))

            for idx, member in enumerate(
                (name for position, name in enumerate(members) if position != reference_index),
                start=1,
            ):
                target = root / f"candidate_{idx:02d}.wav"
                target.write_bytes(zf.read(member))
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
