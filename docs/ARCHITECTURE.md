# Architecture

```text
Audio / Video
    |
    v
FFmpeg decode -> mono PCM WAV
    |
    +-> .venv-diarization / pyannote (CPU subprocess, one model load for all clips)
    |
    v
Reference selection
    |
    v
.venv / Chatterbox Multilingual V3 (CUDA)
    |                |
    |                +-> preview.wav
    +-> conditioning.pt
    |
    v
.mrvoice package
    |
    +-> download
    +-> ~/.kaliv/voices/ (same-host ModelRig)
    +-> optional remote ModelRig API later
```

The UI intentionally exposes no model knobs in the normal flow.

## Why two Python environments?

Chatterbox 0.1.7 pins `torch==2.6.0` and `torchaudio==2.6.0`, while current
pyannote.audio requires PyTorch 2.8 or newer. That dependency graph cannot be
satisfied safely in one environment. VoiceRig therefore treats the split as an
architecture boundary rather than fighting pip:

- `.venv`: VoiceRig app + Chatterbox + official CUDA-enabled PyTorch 2.6.0.
- `.venv-diarization`: current pyannote + CPU-only PyTorch.

Diarization receives normalized WAV paths over a tiny subprocess/JSON protocol.
All uploaded clips are processed in one worker invocation so pyannote is loaded
only once per voice build.

## GPU/VRAM budget (MVP invariant)

VoiceRig targets a single 12 GB NVIDIA GPU. The device split is deliberate:

- Chatterbox Multilingual V3 owns CUDA.
- pyannote diarization is CPU-only by construction.
- Only one voice-build job may run at a time.
- Chatterbox is cached instead of reloaded for each operation.
- ModelRig can use the same Chatterbox runtime through VoiceRig's loopback TTS sidecar.

This keeps speaker analysis from contending for GPU VRAM and removes the
Chatterbox/pyannote PyTorch-version conflict at the same time.
