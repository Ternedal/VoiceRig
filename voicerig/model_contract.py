"""Pinned ML/runtime identifiers that define VoiceRig v1's voice contract."""

CHATTERBOX_ENGINE = "chatterbox-multilingual"
CHATTERBOX_MODEL = "v3"
CHATTERBOX_SOURCE_REVISION = "5de7a54aa4e5e2baadb0182dde554908b48b85c2"

DEFAULT_TTS_EXAGGERATION = 0.5
DEFAULT_TTS_CFG_WEIGHT = 0.5
DEFAULT_TTS_TEMPERATURE = 0.8

# Chatterbox's multilingual guidance recommends cfg_weight=0 when unwanted
# reference/accent transfer needs to be minimized. Physical RC14 listening of a
# Danish-on-Danish clone sounded Swedish-like, so RC15 tests that recommendation
# only for Danish while keeping every other generation control unchanged.
DANISH_TTS_CFG_WEIGHT = 0.0


def tts_defaults(language: str) -> dict[str, float]:
    base_language = (language or "").strip().lower().split("-", 1)[0]
    return {
        "exaggeration": DEFAULT_TTS_EXAGGERATION,
        "cfg_weight": DANISH_TTS_CFG_WEIGHT if base_language == "da" else DEFAULT_TTS_CFG_WEIGHT,
        "temperature": DEFAULT_TTS_TEMPERATURE,
    }


PYANNOTE_PACKAGE_VERSION = "4.0.7"
PYANNOTE_MODEL_ID = "pyannote/speaker-diarization-community-1"
DIARIZATION_TORCH_VERSION = "2.8.0"
DIARIZATION_TORCHAUDIO_VERSION = "2.8.0"
DIARIZATION_TORCHCODEC_VERSION = "0.7.0"
DIARIZATION_AUDIO_INPUT = "in-memory-pcm16-wav"

MODEL_READINESS_SCHEMA = 1
