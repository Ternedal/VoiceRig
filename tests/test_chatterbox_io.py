from pathlib import Path

from voicerig.engines.chatterbox import _save_pcm16


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
