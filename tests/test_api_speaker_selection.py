from fastapi.testclient import TestClient

import voicerig.app.main as main
from voicerig.app.pipeline import SpeakerSelectionRequired


def test_ambiguous_speaker_response_is_structured_409(monkeypatch):
    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    choices = [
        {
            "choice": 1,
            "anchor": "0:3.000",
            "label": "Stemme 1",
            "speech_seconds": 8.0,
            "preview_duration": 4.0,
            "preview_wav_base64": "UklGRg==",
        },
        {
            "choice": 2,
            "anchor": "0:9.000",
            "label": "Stemme 2",
            "speech_seconds": 7.5,
            "preview_duration": 4.0,
            "preview_wav_base64": "UklGRg==",
        },
    ]

    def ambiguous(*args, **kwargs):
        raise SpeakerSelectionRequired(choices)

    monkeypatch.setattr(main, "create_voice", ambiguous)
    client = TestClient(main.app)
    response = client.post(
        "/api/voices",
        data={"name": "Interview", "language": "da", "install_in_modelrig": "false"},
        files={"files": ("clip.mp4", b"fake", "video/mp4")},
    )

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "speaker_selection_required"
    assert detail["speakers"] == choices
    assert "Vælg" in detail["message"]


def test_speaker_choice_is_bounded_before_processing(monkeypatch):
    monkeypatch.setenv("VOICERIG_ALLOW_LAN", "1")
    client = TestClient(main.app)
    response = client.post(
        "/api/voices",
        data={"name": "Interview", "speaker_choice": "5"},
        files={"files": ("clip.mp4", b"fake", "video/mp4")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Ugyldigt stemmevalg."
