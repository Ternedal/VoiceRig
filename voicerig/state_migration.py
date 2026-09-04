from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import tarfile
import tempfile
import time
from pathlib import Path
from typing import BinaryIO

from voicerig.config import data_dir
from voicerig.modelrig.client import _local_voices_dir
from voicerig.profiles.package import validate_package

MIGRATION_SCHEMA = 1
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_RESUMABLE_STATES = {"queued", "running", "needs_speaker", "needs_reference"}
_KNOWN_STATES = _RESUMABLE_STATES | {"cancelling", "succeeded", "failed", "cancelled"}
_MAX_JOB_METADATA_BYTES = 2 * 1024 * 1024
_MAX_MANIFEST_BYTES = 4 * 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_stream(stream: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    for block in iter(lambda: stream.read(1024 * 1024), b""):
        total += len(block)
        digest.update(block)
    return digest.hexdigest(), total


def _safe_filename(name: str, suffix: str | None = None) -> str:
    value = str(name or "").strip()
    if not value or Path(value).name != value or "/" in value or "\\" in value:
        raise ValueError(f"Ugyldigt filnavn i migrationsdata: {name!r}")
    if suffix and not value.lower().endswith(suffix.lower()):
        raise ValueError(f"Ugyldig filtype i migrationsdata: {value}")
    return value


def _load_job_metadata(path: Path) -> dict:
    if path.is_symlink():
        raise ValueError(f"Symlink accepteres ikke som VoiceRig-jobmetadata: {path}")
    if path.stat().st_size > _MAX_JOB_METADATA_BYTES:
        raise ValueError(f"VoiceRig-jobmetadata er for stor: {path.name}")
    if not _JOB_ID.fullmatch(path.stem):
        raise ValueError(f"Ugyldigt VoiceRig job-id i filnavn: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Ugyldig VoiceRig-jobmetadata: {path.name}") from exc
    if not isinstance(payload, dict) or payload.get("id") != path.stem:
        raise ValueError(f"VoiceRig-jobmetadata matcher ikke filnavnet: {path.name}")
    state = payload.get("state")
    if state not in _KNOWN_STATES:
        raise ValueError(f"Ukendt VoiceRig-jobtilstand i {path.name}: {state!r}")
    inputs = payload.get("inputs") or []
    if not isinstance(inputs, list):
        raise ValueError(f"VoiceRig-job inputs er ugyldige i {path.name}")
    for item in inputs:
        _safe_filename(item)
    return payload


def _collect_voice_packages(
    data_root: Path,
    modelrig_voices_root: Path,
) -> tuple[dict[str, Path], str | None]:
    found: dict[str, tuple[Path, str]] = {}
    library = data_root / "voices"
    for root in (library, modelrig_voices_root):
        if not root.is_dir():
            continue
        for package in sorted(root.glob("*.mrvoice")):
            if not package.is_file():
                continue
            if package.is_symlink():
                raise ValueError(f"Symlink accepteres ikke som stemmeprofil: {package}")
            _safe_filename(package.name, ".mrvoice")
            validate_package(package)
            digest = _sha256_file(package)
            previous = found.get(package.name)
            if previous and previous[1] != digest:
                raise ValueError(
                    f"Stemmen {package.name} findes i to forskellige versioner i "
                    "VoiceRig og ModelRig. Afklar hvilken der er autoritativ før migration."
                )
            if previous is None or root == library:
                found[package.name] = (package, digest)

    default_name: str | None = None
    marker = modelrig_voices_root / "default.txt"
    if marker.is_file():
        if marker.is_symlink():
            raise ValueError("ModelRig default-stemmemarkøren må ikke være et symlink.")
        try:
            candidate = marker.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError("ModelRig default-stemmemarkøren kunne ikke læses.") from exc
        default_name = _safe_filename(candidate, ".mrvoice")
        if default_name not in found:
            raise ValueError(
                "ModelRig default-stemmen findes ikke som en gyldig .mrvoice-pakke."
            )
    return {name: value[0] for name, value in found.items()}, default_name


def _collect_jobs(data_root: Path) -> tuple[list[tuple[str, Path]], bool, int]:
    jobs_root = data_root / "jobs"
    if not jobs_root.is_dir():
        return [], False, 0

    files: list[tuple[str, Path]] = []
    contains_private_inputs = False
    job_count = 0
    for metadata in sorted(jobs_root.glob("*.json")):
        if not metadata.is_file():
            continue
        payload = _load_job_metadata(metadata)
        job_id = metadata.stem
        job_count += 1
        files.append((f"jobs/{metadata.name}", metadata))

        state = payload["state"]
        if state not in _RESUMABLE_STATES:
            continue
        inputs = payload.get("inputs") or []
        if not inputs:
            raise ValueError(
                f"Job {job_id} står som {state}, men har ingen migrerbare inputfiler."
            )
        work = jobs_root / job_id
        if not work.is_dir():
            raise ValueError(
                f"Job {job_id} står som {state}, men jobmappen med private inputfiler mangler."
            )
        if work.is_symlink():
            raise ValueError(f"Symlink accepteres ikke som VoiceRig-jobmappe: {work}")
        for name in inputs:
            safe = _safe_filename(name)
            source = work / safe
            if not source.is_file():
                raise ValueError(
                    f"Job {job_id} kan ikke genoptages: inputfilen {safe} mangler."
                )
            if source.is_symlink():
                raise ValueError(f"Symlink accepteres ikke som VoiceRig-jobinput: {source}")
            files.append((f"jobs/{job_id}/{safe}", source))
            contains_private_inputs = True
    return files, contains_private_inputs, job_count


def _manifest_from_live(
    data_root: Path,
    modelrig_voices_root: Path,
) -> tuple[dict, list[tuple[str, Path]]]:
    voices, default_name = _collect_voice_packages(data_root, modelrig_voices_root)
    jobs, contains_private_inputs, job_count = _collect_jobs(data_root)

    live_files: list[tuple[str, Path]] = []
    for name, path in sorted(voices.items()):
        live_files.append((f"voices/{name}", path))
    live_files.extend(jobs)

    records: dict[str, dict] = {}
    for archive_name, path in live_files:
        records[archive_name] = {
            "sha256": _sha256_file(path),
            "size": path.stat().st_size,
        }

    manifest = {
        "schema": MIGRATION_SCHEMA,
        "created": time.strftime("%Y%m%d-%H%M%S", time.localtime()),
        "files": records,
        "default_package": default_name,
        "voice_count": len(voices),
        "job_count": job_count,
        "contains_private_job_inputs": contains_private_inputs,
    }
    return manifest, live_files


def create(
    out_dir: str | os.PathLike[str] = ".",
    *,
    data_root: Path | None = None,
    modelrig_voices_root: Path | None = None,
) -> str:
    root = (data_root or data_dir()).expanduser().resolve()
    modelrig_root = (modelrig_voices_root or _local_voices_dir()).expanduser().resolve()
    manifest, live_files = _manifest_from_live(root, modelrig_root)

    output = Path(out_dir).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"voicerig-migration-{manifest['created']}.tar.gz"
    temp = archive.with_name(archive.name + ".tmp")
    temp.unlink(missing_ok=True)

    try:
        with tarfile.open(temp, "w:gz") as tar:
            for archive_name, source in live_files:
                tar.add(source, arcname=f"data/{archive_name}", recursive=False)
            payload = json.dumps(
                manifest,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            info = tarfile.TarInfo("manifest.json")
            info.size = len(payload)
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(payload))
        os.replace(temp, archive)
    finally:
        temp.unlink(missing_ok=True)

    verify(str(archive))
    return str(archive)


def _read_manifest(tar: tarfile.TarFile) -> dict:
    try:
        member = tar.getmember("manifest.json")
    except KeyError as exc:
        raise ValueError("Ikke et VoiceRig-migrationsarkiv: manifest.json mangler.") from exc
    if not member.isfile() or member.size > _MAX_MANIFEST_BYTES:
        raise ValueError("VoiceRig migration manifest.json er ugyldig eller for stor.")
    handle = tar.extractfile(member)
    if handle is None:
        raise ValueError("VoiceRig migration manifest.json kunne ikke læses.")
    try:
        payload = json.loads(handle.read().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("VoiceRig migration manifest.json er ugyldig JSON.") from exc
    if not isinstance(payload, dict) or payload.get("schema") != MIGRATION_SCHEMA:
        schema = payload.get("schema") if isinstance(payload, dict) else None
        raise ValueError(f"Ikke-understøttet VoiceRig migrationsschema: {schema!r}")
    files = payload.get("files")
    if not isinstance(files, dict):
        raise ValueError("VoiceRig migrationsmanifestet mangler files-objektet.")
    return payload


def _validate_manifest_file_entry(name: str, metadata: object) -> tuple[str, int]:
    if not isinstance(name, str) or not name or name.startswith("/") or "\\" in name:
        raise ValueError(f"Ugyldigt arkivnavn i VoiceRig-manifest: {name!r}")
    if ".." in Path(name).parts:
        raise ValueError(f"Path traversal i VoiceRig-manifest: {name}")
    if not isinstance(metadata, dict):
        raise ValueError(f"Ugyldig metadata for {name}")
    digest = metadata.get("sha256")
    size = metadata.get("size")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError(f"Ugyldig SHA-256 for {name}")
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        raise ValueError(f"Ugyldig filstørrelse for {name}")
    return digest, size


def _validate_job_payload_bytes(
    archive_name: str,
    payload_bytes: bytes,
    archive_names: set[str],
) -> set[str]:
    if len(payload_bytes) > _MAX_JOB_METADATA_BYTES:
        raise ValueError(f"Jobmetadata er for stor i arkivet: {archive_name}")
    job_file = Path(archive_name)
    if len(job_file.parts) != 2 or job_file.parts[0] != "jobs":
        raise ValueError(f"Ugyldig jobmetadata-sti: {archive_name}")
    if not _JOB_ID.fullmatch(job_file.stem):
        raise ValueError(f"Ugyldigt job-id i arkivet: {archive_name}")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Ugyldig jobmetadata i arkivet: {archive_name}") from exc
    if not isinstance(payload, dict) or payload.get("id") != job_file.stem:
        raise ValueError(f"Jobmetadata matcher ikke filnavnet i arkivet: {archive_name}")
    state = payload.get("state")
    if state not in _KNOWN_STATES:
        raise ValueError(f"Ukendt jobtilstand i arkivet: {state!r}")
    inputs = payload.get("inputs") or []
    if not isinstance(inputs, list):
        raise ValueError(f"Ugyldige jobinputs i arkivet: {archive_name}")

    expected_inputs: set[str] = set()
    for item in inputs:
        safe = _safe_filename(item)
        if state in _RESUMABLE_STATES:
            expected = f"jobs/{job_file.stem}/{safe}"
            expected_inputs.add(expected)
            if expected not in archive_names:
                raise ValueError(
                    f"Job {job_file.stem} kan ikke genoptages: {safe} mangler i arkivet."
                )
    return expected_inputs


def _validate_voice_member(tar: tarfile.TarFile, archive_name: str) -> None:
    member = tar.getmember(f"data/{archive_name}")
    handle = tar.extractfile(member)
    if handle is None:
        raise ValueError(f"Stemmen {archive_name} kunne ikke læses fra migrationsarkivet.")
    with tempfile.NamedTemporaryFile(suffix=".mrvoice", delete=False) as temporary:
        temp_path = Path(temporary.name)
        shutil.copyfileobj(handle, temporary)
    try:
        validate_package(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def verify(archive: str | os.PathLike[str]) -> dict:
    path = Path(archive).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(str(path))

    with tarfile.open(path, "r:gz") as tar:
        manifest = _read_manifest(tar)
        expected = manifest["files"]
        expected_names = set(expected)

        members = tar.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)):
            raise ValueError("Migrationsarkivet indeholder dublerede tar-medlemmer.")

        actual_data_names: set[str] = set()
        for member in members:
            if member.name == "manifest.json":
                continue
            if not member.isfile() or not member.name.startswith("data/"):
                raise ValueError(f"Uventet tar-medlem i VoiceRig-migration: {member.name}")
            relative = member.name[5:]
            if relative.startswith("/") or "\\" in relative or ".." in Path(relative).parts:
                raise ValueError(f"Ugyldig sti i VoiceRig-migrationsarkivet: {relative}")
            actual_data_names.add(relative)

        if actual_data_names != expected_names:
            missing = sorted(expected_names - actual_data_names)
            extra = sorted(actual_data_names - expected_names)
            raise ValueError(
                f"VoiceRig migrationsinventory mismatch; missing={missing}, extra={extra}"
            )

        checked = 0
        job_payloads: list[tuple[str, bytes]] = []
        for name, metadata in expected.items():
            want_digest, want_size = _validate_manifest_file_entry(name, metadata)
            member = tar.getmember(f"data/{name}")
            if member.size != want_size:
                raise ValueError(f"Filstørrelse matcher ikke manifestet for {name}")
            handle = tar.extractfile(member)
            if handle is None:
                raise ValueError(f"Kunne ikke læse {name} fra migrationsarkivet.")
            if name.startswith("jobs/") and name.endswith(".json"):
                payload = handle.read()
                digest = hashlib.sha256(payload).hexdigest()
                size = len(payload)
                job_payloads.append((name, payload))
            else:
                digest, size = _sha256_stream(handle)
            if digest != want_digest or size != want_size:
                raise ValueError(f"Checksum-fejl i VoiceRig-migrationsarkivet: {name}")
            checked += 1

        for name in sorted(expected_names):
            if name.startswith("voices/"):
                filename = name.split("/", 1)[1]
                _safe_filename(filename, ".mrvoice")
                _validate_voice_member(tar, name)

        expected_job_inputs: set[str] = set()
        for name, payload in job_payloads:
            expected_job_inputs.update(
                _validate_job_payload_bytes(name, payload, expected_names)
            )
        actual_job_inputs = {
            name
            for name in expected_names
            if len(Path(name).parts) == 3 and Path(name).parts[0] == "jobs"
        }
        if actual_job_inputs != expected_job_inputs:
            extra = sorted(actual_job_inputs - expected_job_inputs)
            missing = sorted(expected_job_inputs - actual_job_inputs)
            raise ValueError(
                f"VoiceRig job-input inventory mismatch; missing={missing}, extra={extra}"
            )

        default_name = manifest.get("default_package")
        if default_name is not None:
            safe_default = _safe_filename(default_name, ".mrvoice")
            if f"voices/{safe_default}" not in expected_names:
                raise ValueError("Default-stemmen mangler i VoiceRig-migrationsarkivet.")

        return {
            "ok": True,
            "schema": MIGRATION_SCHEMA,
            "checked": checked,
            "voice_count": int(manifest.get("voice_count") or 0),
            "job_count": int(manifest.get("job_count") or 0),
            "default_package": default_name,
            "contains_private_job_inputs": bool(
                manifest.get("contains_private_job_inputs")
            ),
        }


def _target_for(relative: str, data_root: Path) -> Path:
    parts = Path(relative).parts
    if len(parts) == 2 and parts[0] == "voices":
        return data_root / "voices" / _safe_filename(parts[1], ".mrvoice")
    if len(parts) == 2 and parts[0] == "jobs" and parts[1].endswith(".json"):
        stem = Path(parts[1]).stem
        if not _JOB_ID.fullmatch(stem):
            raise ValueError(f"Ugyldigt job-id i restore: {relative}")
        return data_root / "jobs" / parts[1]
    if len(parts) == 3 and parts[0] == "jobs":
        job_id = parts[1]
        if not _JOB_ID.fullmatch(job_id):
            raise ValueError(f"Ugyldigt job-id i restore: {relative}")
        return data_root / "jobs" / job_id / _safe_filename(parts[2])
    raise ValueError(f"Ukendt VoiceRig migrationssti: {relative}")


def _extract_atomic(tar: tarfile.TarFile, member_name: str, destination: Path) -> None:
    member = tar.getmember(member_name)
    handle = tar.extractfile(member)
    if handle is None:
        raise ValueError(f"Kunne ikke læse {member_name} fra migrationsarkivet.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{destination.name}-",
        suffix=".migration.tmp",
        dir=destination.parent,
    )
    temporary = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            shutil.copyfileobj(handle, output)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def restore(
    archive: str | os.PathLike[str],
    *,
    force: bool = False,
    data_root: Path | None = None,
    modelrig_voices_root: Path | None = None,
) -> dict:
    check = verify(archive)
    path = Path(archive).expanduser().resolve()
    root = (data_root or data_dir()).expanduser().resolve()
    modelrig_root = (modelrig_voices_root or _local_voices_dir()).expanduser().resolve()

    with tarfile.open(path, "r:gz") as tar:
        manifest = _read_manifest(tar)
        files = manifest["files"]
        targets = {name: _target_for(name, root) for name in files}

        default_name = manifest.get("default_package")
        default_target: Path | None = None
        marker: Path | None = None
        if default_name is not None:
            safe_default = _safe_filename(default_name, ".mrvoice")
            default_target = modelrig_root / safe_default
            marker = modelrig_root / "default.txt"

        clashes: list[str] = []
        for destination in targets.values():
            if destination.exists():
                clashes.append(str(destination))
        active_job_dirs = {
            root / "jobs" / Path(name).parts[1]
            for name in files
            if len(Path(name).parts) == 3 and Path(name).parts[0] == "jobs"
        }
        for directory in active_job_dirs:
            if directory.exists():
                clashes.append(str(directory))
        for destination in (default_target, marker):
            if destination is not None and destination.exists():
                clashes.append(str(destination))

        if clashes and not force:
            raise FileExistsError(
                "VoiceRig restore nægter at overskrive eksisterende state uden --force: "
                + ", ".join(sorted(set(clashes)))
            )

        if force:
            for directory in active_job_dirs:
                if directory.exists():
                    shutil.rmtree(directory)

        restored: list[str] = []
        for name, destination in targets.items():
            _extract_atomic(tar, f"data/{name}", destination)
            restored.append(str(destination))

        if default_name is not None and default_target is not None and marker is not None:
            source = root / "voices" / default_name
            if not source.is_file():
                raise RuntimeError(
                    "Default-stemmen blev ikke restaureret til VoiceRig-biblioteket."
                )
            modelrig_root.mkdir(parents=True, exist_ok=True)
            descriptor, temp_name = tempfile.mkstemp(
                prefix=f".{default_target.name}-",
                suffix=".migration.tmp",
                dir=modelrig_root,
            )
            temporary = Path(temp_name)
            try:
                with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output)
                validate_package(temporary)
                os.replace(temporary, default_target)
            finally:
                temporary.unlink(missing_ok=True)
            marker_temp = modelrig_root / "default.txt.migration.tmp"
            marker_temp.write_text(default_name + "\n", encoding="utf-8")
            os.replace(marker_temp, marker)
            restored.extend([str(default_target), str(marker)])

    return {
        "ok": True,
        "restored": restored,
        "voice_count": check["voice_count"],
        "job_count": check["job_count"],
        "default_package": check["default_package"],
        "contains_private_job_inputs": check["contains_private_job_inputs"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voicerig-state-migration")
    subcommands = parser.add_subparsers(dest="command", required=True)

    create_command = subcommands.add_parser("create")
    create_command.add_argument("--out", default=".")

    verify_command = subcommands.add_parser("verify")
    verify_command.add_argument("archive")

    restore_command = subcommands.add_parser("restore")
    restore_command.add_argument("archive")
    restore_command.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "create":
        print(create(args.out))
        return 0
    if args.command == "verify":
        print(json.dumps(verify(args.archive), ensure_ascii=False, indent=2))
        return 0
    if args.command == "restore":
        print(json.dumps(restore(args.archive, force=args.force), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
