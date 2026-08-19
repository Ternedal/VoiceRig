from pathlib import Path
from types import SimpleNamespace
import sys

import voicerig.engines.chatterbox as chatterbox
from voicerig.engines.chatterbox import ChatterboxEngine, _save_pcm16


def test_save_pcm16_pins_wav_encoding_and_bit_depth(tmp_path: Path):
    captured = {}

    class FakeTorchaudio:
        @staticmethod
        def save(path, wav, sample_rate, **kwargs):
            captured.update(
                path=path,
                wav=wav,
                sample_rate=sample_rate,
                kwargs=kwargs,
            )

    marker = object()
    target = tmp_path / "speech.wav"
    _save_pcm16(FakeTorchaudio, target, marker, 24000)

    assert captured["path"] == str(target)
    assert captured["wav"] is marker
    assert captured["sample_rate"] == 24000
    assert captured["kwargs"] == {
        "format": "wav",
        "encoding": "PCM_S",
        "bits_per_sample": 16,
    }


def test_preview_reuses_prepared_conditioning_without_audio_prompt(tmp_path: Path, monkeypatch):
    generated = {}
    saved = {}
    marker = object()

    class FakeModel:
        conds = object()
        sr = 24000

        def generate(self, text, **kwargs):
            generated["text"] = text
            generated["kwargs"] = kwargs
            return marker

    fake_torchaudio = SimpleNamespace(
        save=lambda path, wav, sample_rate, **kwargs: saved.update(
            path=path, wav=wav, sample_rate=sample_rate, kwargs=kwargs
        )
    )
    monkeypatch.setattr(chatterbox, "_shared_model", lambda: FakeModel())
    monkeypatch.setitem(sys.modules, "torchaudio", fake_torchaudio)

    output = tmp_path / "preview.wav"
    ChatterboxEngine(language="da").preview(tmp_path / "reference.wav", output)

    assert "audio_prompt_path" not in generated["kwargs"]
    assert generated["kwargs"]["language_id"] == "da"
    assert saved["wav"] is marker
    assert saved["kwargs"]["encoding"] == "PCM_S"
    assert saved["kwargs"]["bits_per_sample"] == 16
