"""Pinned ML/runtime identifiers that define VoiceRig v1's voice contract."""

CHATTERBOX_ENGINE = "chatterbox-multilingual"
CHATTERBOX_MODEL = "v3"
CHATTERBOX_SOURCE_REVISION = "5de7a54aa4e5e2baadb0182dde554908b48b85c2"

# Danish quality comparison candidate. Røst v3 500M is a Danish-finetuned
# Chatterbox Multilingual checkpoint from the Alexandra Institute / CoRal
# project. Keep the Hugging Face revision immutable so a physical A/B verdict
# always refers to the exact same weights.
ROST_DANISH_ENGINE = CHATTERBOX_ENGINE
ROST_DANISH_MODEL = "roest-v3-chatterbox-500m"
ROST_DANISH_REPO_ID = "CoRal-project/roest-v3-chatterbox-500m"
ROST_DANISH_REVISION = "cd451fdc474aabd229fa0c6b6818f4b34382917e"
ROST_DANISH_TEMPERATURE = 0.8
ROST_DANISH_CFG_WEIGHT = 0.5
ROST_DANISH_REPETITION_PENALTY = 2.0
ROST_DANISH_MIN_P = 0.05
ROST_DANISH_TOP_P = 0.95

# Independent Danish A/B/C candidate. OmniVoice uses a separate runtime so its
# newer Transformers/Torch dependency surface cannot mutate the verified
# Chatterbox environment. Pin both source and model snapshots so physical
# listening always compares the same implementation and weights.
OMNIVOICE_ENGINE = "omnivoice"
OMNIVOICE_MODEL = "k2-fsa/OmniVoice"
OMNIVOICE_SOURCE_REVISION = "38e992bc60f85548faeb77e8fa70158ba71deb30"
OMNIVOICE_PACKAGE_VERSION = "0.2.1"
OMNIVOICE_MODEL_REVISION = "c5fdb5ccb189668d56333f77ba2629f4cd7535f4"
OMNIVOICE_ASR_MODEL = "openai/whisper-large-v3-turbo"
OMNIVOICE_ASR_REVISION = "cf7667b3865845227378e06c611d63789cbcdcce"
OMNIVOICE_TORCH_VERSION = "2.8.0"
OMNIVOICE_TORCHAUDIO_VERSION = "2.8.0"
OMNIVOICE_CUDA_INDEX = "https://download.pytorch.org/whl/cu128"

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
