from pathlib import Path
import shutil

from voicerig.profiles.library import (
    delete_voice,
    import_package,
    list_voices,
    preview_wav,
    set_default,
)
from voicerig.profiles.package import build_package, validate_package


def _package(tmp_path: Path, name: str, filename: str) -> Path:
    work = tmp_path / f"src-{filename}"
    work.mkdir()
    ref = work / "reference.wav"; ref.write_bytes(b"RIFF-reference")
    cond = work / "conditioning.pt"; cond.write_bytes(b"conditioning")
    preview = work / "preview.wav"; preview.write_bytes(b"RIFF-preview")
    package = work / filename
    build_package(name, "da", ref, cond, preview, package)
    return package


def _env(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    data = tmp_path / "data"
    modelrig = tmp_path / "modelrig-voices"
    monkeypatch.setenv("VOICERIG_DATA_DIR", str(data))
    monkeypatch.setenv("MODELRIG_VOICES_DIR", str(modelrig))
    return data / "voices", modelrig


def test_library_lists_voice_from_both_locations_once(monkeypatch, tmp_path: Path):
    library, modelrig = _env(monkeypatch, tmp_path)
    library.mkdir(parents=True)
    modelrig.mkdir(parents=True)
    source = _package(tmp_path, "Anders", "anders.mrvoice")
    shutil.copy2(source, library / source.name)
    shutil.copy2(source, modelrig / source.name)
    (modelrig / "default.txt").write_text("anders.mrvoice\n", encoding="utf-8")

    result = list_voices()

    assert result["default_package"] == "anders.mrvoice"
    assert len(result["voices"]) == 1
    voice = result["voices"][0]
    assert voice["name"] == "Anders"
    assert voice["is_default"] is True
    assert voice["in_library"] is True
    assert voice["installed_in_modelrig"] is True


def test_library_keeps_corrupt_profile_visible(monkeypatch, tmp_path: Path):
    library, _modelrig = _env(monkeypatch, tmp_path)
    library.mkdir(parents=True)
    (library / "broken.mrvoice").write_bytes(b"not-a-zip")

    result = list_voices()

    assert result["voices"] == []
    assert result["invalid"][0]["package"] == "broken.mrvoice"


def test_import_preview_activate_and_delete(monkeypatch, tmp_path: Path):
    library, modelrig = _env(monkeypatch, tmp_path)
    source = _package(tmp_path, "Imported", "imported.mrvoice")

    imported = import_package(source, "imported.mrvoice")
    assert imported["package"] == "imported.mrvoice"
    assert validate_package(library / "imported.mrvoice")["name"] == "Imported"
    assert preview_wav("imported.mrvoice") == b"RIFF-preview"

    activated = set_default("imported.mrvoice")
    assert activated["voice"]["is_default"] is True
    assert (modelrig / "imported.mrvoice").is_file()
    assert (modelrig / "default.txt").read_text(encoding="utf-8").strip() == "imported.mrvoice"

    deleted = delete_voice("imported.mrvoice")
    assert deleted["ok"] is True
    assert not (library / "imported.mrvoice").exists()
    assert not (modelrig / "imported.mrvoice").exists()
    assert not (modelrig / "default.txt").exists()


def test_import_collision_with_different_voice_id_gets_unique_filename(monkeypatch, tmp_path: Path):
    library, _modelrig = _env(monkeypatch, tmp_path)
    library.mkdir(parents=True)
    first = _package(tmp_path, "Same Name", "one.mrvoice")
    second = _package(tmp_path, "Same Name", "two.mrvoice")
    shutil.copy2(first, library / "same.mrvoice")

    imported = import_package(second, "same.mrvoice")

    assert imported["package"] != "same.mrvoice"
    assert imported["package"].startswith("same-name-")
    assert (library / imported["package"]).is_file()
