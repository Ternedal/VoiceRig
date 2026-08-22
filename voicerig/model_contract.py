"""Pinned ML/runtime identifiers that define VoiceRig v1's voice contract."""

CHATTERBOX_ENGINE = "chatterbox-multilingual"
CHATTERBOX_MODEL = "v3"
CHATTERBOX_SOURCE_REVISION = "5de7a54aa4e5e2baadb0182dde554908b48b85c2"

# Chatterbox's own multilingual guidance recommends cfg_weight=0 when
# reference/accent transfer is undesirable. VoiceRig uses Danish references
# with Danish synthesis, but physical RC14 listening still sounded Swedish-like,
# so V1 pins the Danish profile default to the accent-minimizing setting while
# leaving the other generation controls unchanged for a clean A/B comparison.
DANISH_TTS_EXAGGERATION = 0.5
DANISH_TTS_CFG_WEIGHT = 0.0
DANISH_TTS_TEMPERATURE = 0.8

PYANNOTE_PACKAGE_VERSION = "4.0.7"
PYANNOTE_MODEL_ID = "pyannote/speaker-diarization-community-1"
DIARIZATION_TORCH_VERSION = "2.8.0"
DIARIZATION_TORCHAUDIO_VERSION = "2.8.0"
DIARIZATION_TORCHCODEC_VERSION = "0.7.0"
DIARIZATION_AUDIO_INPUT = "in-memory-pcm16-wav"

MODEL_READINESS_SCHEMA = 1
