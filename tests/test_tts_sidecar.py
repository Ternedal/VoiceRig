from pathlib import Path

import voicerig.engines.chatterbox as chatterbox
import voicerig.engines.package_runtime as package_runtime
from voicerig.engines.chatterbox import ChatterboxEngine
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


def test_voice_build_invalidates_previous_package_conditioning_identity(tmp_path: Path, monkeypatch):
    calls = []

    class FakeConds:
        def save(self, path):
            Path(path).write_bytes(b"conditioning")

    class FakeModel:
        conds = FakeConds()

        def prepare_conditionals(self, path, exaggeration=0.5):
            calls.append(path)
            self.conds = FakeConds()

    model = FakeModel()
    reference = tmp_path / "new-reference.wav"
    reference.write_bytes(b"reference")
    conditioning = tmp_path / "new-conditioning.pt"

    chatterbox._set_conditioning_key(("package", "old-voice", "cuda"))
    monkeypatch.setattr(chatterbox, "_shared_model", lambda: model)

    ChatterboxEngine().build_conditioning(reference, conditioning)

    assert chatterbox._conditioning_key() == ("build", str(reference.resolve()))

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "reference.wav").write_bytes(b"reference")
    (cache / "conditioning.pt").write_bytes(b"not-a-real-torch-file")
    monkeypatch.setattr(package_runtime, "_materialize", lambda *_args: cache)

    package_runtime._ensure_conditioning(
        model,
        tmp_path / "installed.mrvoice",
        {"id": "old-voice"},
        "cuda",
    )

    # The stale package key could not short-circuit because the build changed
    # the shared model identity. With no real Chatterbox dependency in CI, the
    # loader falls back to prepare_conditionals(reference.wav), which proves the
    # reload path was actually taken.
    assert len(calls) == 2
    assert chatterbox._conditioning_key() == ("package", "old-voice", "cuda")
    chatterbox._set_conditioning_key(None)
