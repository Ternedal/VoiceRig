from __future__ import annotations

import sys
import weakref
from pathlib import Path
from types import ModuleType, SimpleNamespace

import voicerig.engines.chatterbox as chatterbox
import voicerig.engines.rost as rost
from voicerig.model_contract import (
    CHATTERBOX_MODEL,
    CHATTERBOX_SOURCE_REVISION,
    ROST_DANISH_CFG_WEIGHT,
    ROST_DANISH_MODEL,
    ROST_DANISH_REPETITION_PENALTY,
    ROST_DANISH_REPO_ID,
    ROST_DANISH_REVISION,
    ROST_DANISH_TOP_P,
)


def test_rost_loader_uses_exact_huggingface_revision_and_minimal_runtime_files(monkeypatch, tmp_path: Path):
    captured = {}
    fake_chatterbox_package = ModuleType("chatterbox")
    fake_mtl = ModuleType("chatterbox.mtl_tts")

    class FakeMultilingual:
        @classmethod
        def from_local(cls, model_dir, device):
            captured["from_local"] = (model_dir, device)
            return object()

    fake_mtl.ChatterboxMultilingualTTS = FakeMultilingual
    fake_chatterbox_package.mtl_tts = fake_mtl
    fake_hf = ModuleType("huggingface_hub")

    def snapshot_download(**kwargs):
        captured["snapshot"] = kwargs
        return str(tmp_path / "rost")

    fake_hf.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "chatterbox", fake_chatterbox_package)
    monkeypatch.setitem(sys.modules, "chatterbox.mtl_tts", fake_mtl)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hf)

    model = chatterbox._load_model(ROST_DANISH_MODEL, ROST_DANISH_REVISION, "cuda")

    assert model is not None
    assert captured["snapshot"]["repo_id"] == ROST_DANISH_REPO_ID
    assert captured["snapshot"]["revision"] == ROST_DANISH_REVISION
    assert captured["snapshot"]["allow_patterns"] == chatterbox._ROST_REQUIRED_FILES
    assert "t3_mtl23ls_v2.safetensors" in captured["snapshot"]["allow_patterns"]
    assert "t3_23lang.safetensors" not in captured["snapshot"]["allow_patterns"]
    assert "ve.safetensors" not in captured["snapshot"]["allow_patterns"]
    assert captured["from_local"] == (str(tmp_path / "rost"), "cuda")


def test_shared_model_keeps_only_one_large_checkpoint_per_device(monkeypatch):
    loaded = []
    chatterbox._MODELS.clear()
    monkeypatch.setattr(chatterbox, "chatterbox_device", lambda: "cuda")

    def fake_load(model_name, revision, device):
        marker = object()
        loaded.append((model_name, revision, device, marker))
        return marker

    monkeypatch.setattr(chatterbox, "_load_model", fake_load)

    general = chatterbox._shared_model(CHATTERBOX_MODEL, CHATTERBOX_SOURCE_REVISION)
    rost_model = chatterbox._shared_model(ROST_DANISH_MODEL, ROST_DANISH_REVISION)
    rost_again = chatterbox._shared_model(ROST_DANISH_MODEL, ROST_DANISH_REVISION)

    assert general is not rost_model
    assert rost_again is rost_model
    assert len(loaded) == 2
    assert chatterbox._MODELS["cuda"] == ((ROST_DANISH_MODEL, ROST_DANISH_REVISION), rost_model)


def test_shared_model_drops_internal_reference_before_loading_replacement(monkeypatch):
    """The cache itself must not keep the previous GPU model alive during load."""
    chatterbox._MODELS.clear()
    monkeypatch.setattr(chatterbox, "chatterbox_device", lambda: "cuda")

    class OldModel:
        pass

    old = OldModel()
    old_ref = weakref.ref(old)
    chatterbox._MODELS["cuda"] = ((CHATTERBOX_MODEL, CHATTERBOX_SOURCE_REVISION), old)
    del old

    replacement = object()

    def fake_load(model_name, revision, device):
        # _release_device_model() performs gc.collect() before this call. If
        # _shared_model still holds its local `resident` tuple, old_ref() is not
        # None here and the physical GPU checkpoint may still occupy VRAM.
        assert old_ref() is None
        assert (model_name, revision, device) == (
            ROST_DANISH_MODEL,
            ROST_DANISH_REVISION,
            "cuda",
        )
        return replacement

    monkeypatch.setattr(chatterbox, "_load_model", fake_load)

    assert chatterbox._shared_model(ROST_DANISH_MODEL, ROST_DANISH_REVISION) is replacement


def test_rost_synthesis_uses_danish_quality_parameters(monkeypatch, tmp_path: Path):
    generated = {}
    saved = {}

    class FakeWav:
        shape = (1, 48000)

    class FakeModel:
        conds = None
        sr = 24000

        def prepare_conditionals(self, path, exaggeration):
            generated["reference"] = path
            generated["prepare_exaggeration"] = exaggeration
            self.conds = object()

        def generate(self, text, **kwargs):
            generated["text"] = text
            generated["kwargs"] = kwargs
            return FakeWav()

    reference = tmp_path / "reference.wav"
    reference.write_bytes(b"RIFF-reference")
    output = tmp_path / "rost.wav"
    fake_torchaudio = SimpleNamespace(
        save=lambda path, wav, sample_rate, **kwargs: saved.update(
            path=path,
            wav=wav,
            sample_rate=sample_rate,
            kwargs=kwargs,
        )
    )
    monkeypatch.setattr(rost, "_shared_model", lambda model, revision: FakeModel())
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)

    meta = rost.synthesize_rost_danish(reference, "Rødgrød med fløde.", output)

    assert generated["kwargs"]["language_id"] == "da"
    assert generated["kwargs"]["cfg_weight"] == ROST_DANISH_CFG_WEIGHT == 0.5
    assert generated["kwargs"]["repetition_penalty"] == ROST_DANISH_REPETITION_PENALTY == 2.0
    assert generated["kwargs"]["top_p"] == ROST_DANISH_TOP_P == 0.95
    assert saved["sample_rate"] == 24000
    assert saved["kwargs"]["encoding"] == "PCM_S"
    assert meta["model"] == ROST_DANISH_MODEL
    assert meta["revision"] == ROST_DANISH_REVISION
    assert meta["duration"] == 2.0


def test_rost_artifact_build_serializes_selected_reference_conditioning_and_preview(monkeypatch, tmp_path: Path):
    captured = {}

    class FakeConds:
        def save(self, path):
            captured["conditioning_path"] = Path(path)
            Path(path).write_bytes(b"rost-serialized-conditioning")

    class FakeWav:
        shape = (1, 24000)

    class FakeModel:
        conds = None
        sr = 24000

        def prepare_conditionals(self, path, exaggeration):
            captured["reference"] = path
            captured["prepare_exaggeration"] = exaggeration
            self.conds = FakeConds()

        def generate(self, text, **kwargs):
            captured["preview_text"] = text
            captured["kwargs"] = kwargs
            return FakeWav()

    reference = tmp_path / "reference-3.wav"
    conditioning = tmp_path / "conditioning.pt"
    preview = tmp_path / "preview.wav"
    reference.write_bytes(b"RIFF-reference-three")

    fake_torchaudio = SimpleNamespace(
        save=lambda path, wav, sample_rate, **kwargs: Path(path).write_bytes(b"RIFF-rost-preview")
    )
    monkeypatch.setattr(rost, "_shared_model", lambda model, revision: FakeModel())
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)

    result = rost.build_rost_danish_artifacts(reference, conditioning, preview)

    assert result == (conditioning, preview)
    assert captured["reference"] == str(reference)
    assert captured["conditioning_path"] == conditioning
    assert conditioning.read_bytes() == b"rost-serialized-conditioning"
    assert preview.read_bytes() == b"RIFF-rost-preview"
    assert captured["preview_text"] == rost.ROST_DANISH_PREVIEW_TEXT
    assert captured["kwargs"]["language_id"] == "da"
    assert captured["kwargs"]["cfg_weight"] == 0.5
    assert captured["kwargs"]["repetition_penalty"] == 2.0
    assert captured["kwargs"]["min_p"] == 0.05
    assert captured["kwargs"]["top_p"] == 0.95
