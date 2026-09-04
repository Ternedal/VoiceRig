from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest

from voicerig.profiles.package import build_package, validate_package
from voicerig import state_migration


def _package(root: Path, filename: str, name: str) -> Path:
    source = root / f"source-{filename}"
    source.mkdir(parents=True, exist_ok=True)
    reference = source / "reference.wav"
    conditioning = source / "conditioning.pt"
    preview = source / "preview.wav"
    reference.write_bytes(f"RIFF-reference-{name}".encode())
    conditioning.write_bytes(f"conditioning-{name}".encode())
    preview.write_bytes(f"RIFF-preview-{name}".encode())
    package = root / filename
    build_package(name, "da", reference, conditioning, preview, package)
    validate_package(package)
    return package


def _job(root: Path, job_id: str, state: str, inputs: list[str]) -> Path:
    jobs = root / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": job_id,
        "kind": "voice-build",
        "state": state,
        "inputs": inputs,
        "name": "Migration job",
        "language": "da",
        "created_at": "2026-09-04T17:00:00+00:00",
        "updated_at": "2026-09-04T17:00:00+00:00",
    }
    path = jobs / f"{job_id}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _rewrite_member(archive: Path, destination: Path, target: str) -> None:
    with tarfile.open(archive, "r:gz") as source, tarfile.open(destination, "w:gz") as output:
        for member in source.getmembers():
            handle = source.extractfile(member)
            payload = handle.read() if handle is not None else b""
            if member.name == target:
                payload = payload[:-1] + bytes([(payload[-1] ^ 0x01) if payload else 1])
            replacement = tarfile.TarInfo(member.name)
            replacement.size = len(payload)
            replacement.mtime = member.mtime
            output.addfile(replacement, io.BytesIO(payload))


def test_round_trip_profiles_default_jobs_and_exclusions(tmp_path: Path):
    old_data = tmp_path / "old-data"
    old_library = old_data / "voices"
    old_library.mkdir(parents=True)
    old_modelrig = tmp_path / "old-modelrig-voices"
    old_modelrig.mkdir()

    local_voice = _package(old_library, "anders.mrvoice", "Anders")
    modelrig_only = _package(old_modelrig, "modelrig-only.mrvoice", "ModelRig Only")
    (old_modelrig / "default.txt").write_text(modelrig_only.name + "\n", encoding="utf-8")

    active_id = "a" * 32
    _job(old_data, active_id, "queued", ["input_00.wav"])
    active_work = old_data / "jobs" / active_id
    active_work.mkdir()
    private_input = active_work / "input_00.wav"
    private_input.write_bytes(b"private-source-audio")

    terminal_id = "b" * 32
    _job(old_data, terminal_id, "succeeded", [])

    # Machine-local/generated state must never enter a migration archive.
    (old_data / "model-readiness.json").write_text("stale", encoding="utf-8")
    (old_data / "logs").mkdir()
    (old_data / "logs" / "voicerig.log").write_text("log", encoding="utf-8")
    (old_data / "runtimes").mkdir()
    (old_data / "runtimes" / "runtime.bin").write_bytes(b"runtime")
    (old_data / "tts-runtime").mkdir()
    (old_data / "tts-runtime" / "cache.bin").write_bytes(b"cache")
    (old_library / "anders-reference.wav").write_bytes(b"convenience-sidecar")

    archive = Path(
        state_migration.create(
            tmp_path / "exports",
            data_root=old_data,
            modelrig_voices_root=old_modelrig,
        )
    )
    check = state_migration.verify(archive)
    assert check == {
        "ok": True,
        "schema": 1,
        "checked": 5,
        "voice_count": 2,
        "job_count": 2,
        "default_package": modelrig_only.name,
        "contains_private_job_inputs": True,
    }

    new_data = tmp_path / "new-data"
    new_modelrig = tmp_path / "new-modelrig-voices"
    result = state_migration.restore(
        archive,
        data_root=new_data,
        modelrig_voices_root=new_modelrig,
    )
    assert result["ok"] is True
    assert result["voice_count"] == 2
    assert result["job_count"] == 2
    assert result["contains_private_job_inputs"] is True

    restored_local = new_data / "voices" / local_voice.name
    restored_modelrig_only = new_data / "voices" / modelrig_only.name
    assert restored_local.read_bytes() == local_voice.read_bytes()
    assert restored_modelrig_only.read_bytes() == modelrig_only.read_bytes()
    validate_package(restored_local)
    validate_package(restored_modelrig_only)

    assert (new_modelrig / modelrig_only.name).read_bytes() == modelrig_only.read_bytes()
    assert (new_modelrig / "default.txt").read_text(encoding="utf-8").strip() == modelrig_only.name
    assert (new_data / "jobs" / f"{active_id}.json").is_file()
    assert (new_data / "jobs" / active_id / "input_00.wav").read_bytes() == private_input.read_bytes()
    assert (new_data / "jobs" / f"{terminal_id}.json").is_file()

    assert not (new_data / "model-readiness.json").exists()
    assert not (new_data / "logs").exists()
    assert not (new_data / "runtimes").exists()
    assert not (new_data / "tts-runtime").exists()
    assert not (new_data / "voices" / "anders-reference.wav").exists()

    with pytest.raises(FileExistsError, match="--force"):
        state_migration.restore(
            archive,
            data_root=new_data,
            modelrig_voices_root=new_modelrig,
        )

    stale = new_data / "jobs" / active_id / "stale.tmp"
    stale.write_text("must disappear", encoding="utf-8")
    state_migration.restore(
        archive,
        force=True,
        data_root=new_data,
        modelrig_voices_root=new_modelrig,
    )
    assert not stale.exists()
    assert (new_data / "jobs" / active_id / "input_00.wav").read_bytes() == private_input.read_bytes()


def test_corrupt_archive_is_rejected_before_restore_writes(tmp_path: Path):
    old_data = tmp_path / "old"
    voices = old_data / "voices"
    voices.mkdir(parents=True)
    package = _package(voices, "voice.mrvoice", "Voice")
    archive = Path(
        state_migration.create(
            tmp_path / "exports",
            data_root=old_data,
            modelrig_voices_root=tmp_path / "empty-modelrig",
        )
    )
    bad = tmp_path / "bad.tar.gz"
    _rewrite_member(archive, bad, f"data/voices/{package.name}")

    with pytest.raises(ValueError, match="Checksum"):
        state_migration.verify(bad)

    new_data = tmp_path / "new-data"
    with pytest.raises(ValueError, match="Checksum"):
        state_migration.restore(
            bad,
            data_root=new_data,
            modelrig_voices_root=tmp_path / "new-modelrig",
        )
    assert not new_data.exists()


def test_conflicting_same_named_voice_is_fail_closed(tmp_path: Path):
    data_root = tmp_path / "data"
    library = data_root / "voices"
    library.mkdir(parents=True)
    modelrig = tmp_path / "modelrig"
    modelrig.mkdir()
    _package(library, "same.mrvoice", "Library Voice")
    _package(modelrig, "same.mrvoice", "Different Voice")

    with pytest.raises(ValueError, match="to forskellige versioner"):
        state_migration.create(
            tmp_path / "exports",
            data_root=data_root,
            modelrig_voices_root=modelrig,
        )


def test_resumable_job_without_source_input_blocks_export(tmp_path: Path):
    data_root = tmp_path / "data"
    job_id = "c" * 32
    _job(data_root, job_id, "needs_speaker", ["input_00.wav"])
    (data_root / "jobs" / job_id).mkdir()

    with pytest.raises(ValueError, match="inputfilen input_00.wav mangler"):
        state_migration.create(
            tmp_path / "exports",
            data_root=data_root,
            modelrig_voices_root=tmp_path / "modelrig",
        )
