from pathlib import Path

from voicerig.modelrig.client import install_local


def test_local_install_copies_package_and_sets_default(tmp_path: Path, monkeypatch):
    voices = tmp_path / "voices"
    monkeypatch.setenv("MODELRIG_VOICES_DIR", str(voices))
    package = tmp_path / "anders.mrvoice"
    package.write_bytes(b"profile")

    result = install_local(package)

    assert (voices / "anders.mrvoice").read_bytes() == b"profile"
    assert (voices / "default.txt").read_text().strip() == "anders.mrvoice"
    assert result["mode"] == "local"
