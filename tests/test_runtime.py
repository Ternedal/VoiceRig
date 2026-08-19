import voicerig.runtime as runtime


def test_diarization_defaults_to_cpu(monkeypatch):
    monkeypatch.delenv("VOICERIG_DIARIZATION_DEVICE", raising=False)
    assert runtime.diarization_device() == "cpu"


def test_invalid_device_setting_falls_back(monkeypatch):
    monkeypatch.setenv("VOICERIG_DIARIZATION_DEVICE", "potato")
    assert runtime.diarization_device() == "cpu"
