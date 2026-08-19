from pathlib import Path

from voicerig.engines.package_runtime import resolve_package
from voicerig.profiles.package import build_package


def _package(tmp_path: Path, name: str) -> Path:
    reference = tmp_path / f"{name}-reference.wav"
    conditioning = tmp_path / f"{name}-conditioning.pt"
    preview = tmp_path / f"{name}-preview.wav"
    reference.write_bytes(b"reference")
    conditioning.write_bytes(b"conditioning")
    preview.write_bytes(b"preview")
    package = tmp_path / f"{name}.mrvoice"
    return build_package(name, "da", reference, conditioning, preview, package)


def test_sidecar_resolves_modelrig_default(tmp_path: Path, monkeypatch):
    voices = tmp_path / "modelrig-voices"
    voices.mkdir()
    monkeypatch.setenv("MODELRIG_VOICES_DIR", str(voices))

    package = _package(tmp_path, "anders")
    installed = voices / package.name
    installed.write_bytes(package.read_bytes())
    (voices / "default.txt").write_text(installed.name + "\n", encoding="utf-8")

    assert resolve_package() == installed
    assert resolve_package(installed.name) == installed
