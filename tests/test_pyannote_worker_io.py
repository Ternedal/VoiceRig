from __future__ import annotations

import struct
import sys
import wave
from types import SimpleNamespace

import pytest

from voicerig.analysis import pyannote_worker as worker


class FakeTensor:
    def __init__(self, raw):
        self.raw = raw
        self.dtype = None
        self.divisor = None
        self.unsqueeze_dim = None

    def clone(self):
        return self

    def to(self, dtype):
        self.dtype = dtype
        return self

    def div_(self, value):
        self.divisor = value
        return self

    def unsqueeze(self, dim):
        self.unsqueeze_dim = dim
        return self


def test_canonical_pcm16_wav_is_loaded_as_in_memory_waveform(tmp_path, monkeypatch):
    path = tmp_path / "speaker.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(struct.pack("<hhhh", 0, 1000, -1000, 500))

    captured = {}

    def frombuffer(raw, dtype):
        captured["dtype"] = dtype
        captured["bytes"] = bytes(raw)
        return FakeTensor(raw)

    fake_torch = SimpleNamespace(int16="int16", float32="float32", frombuffer=frombuffer)
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    audio = worker._load_canonical_wav(str(path))

    assert audio["sample_rate"] == 24000
    assert audio["uri"] == "speaker"
    assert captured["dtype"] == "int16"
    assert len(captured["bytes"]) == 8
    assert audio["waveform"].dtype == "float32"
    assert audio["waveform"].divisor == 32768.0
    assert audio["waveform"].unsqueeze_dim == 0


def test_canonical_loader_rejects_non_mono_wav(tmp_path, monkeypatch):
    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(struct.pack("<hhhh", 0, 0, 100, 100))

    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(int16="int16", float32="float32", frombuffer=lambda *args, **kwargs: FakeTensor(b"")),
    )

    with pytest.raises(RuntimeError, match="mono PCM16"):
        worker._load_canonical_wav(str(path))
