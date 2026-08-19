# Architecture

```text
Audio / Video
    |
    v
FFmpeg decode -> mono PCM WAV
    |
    +-> pyannote diarization (when available)
    |
    v
Reference selection
    |
    v
Chatterbox Multilingual V3
    |                |
    |                +-> preview.wav
    +-> conditioning.pt
    |
    v
.mrvoice package
    |
    +-> download
    +-> ModelRig backend /api/v1/voices/import
```

The UI intentionally exposes no model knobs in the normal flow.

## GPU/VRAM budget (MVP invariant)

VoiceRig targets a single 12 GB NVIDIA GPU. The default device split is deliberate:

- Chatterbox Multilingual V3: CUDA when available.
- pyannote diarization: CPU by default.
- Only one voice-build job may run at a time.
- Both heavyweight models are cached instead of reloaded per file/request.

This keeps diarization from contending with Chatterbox for VRAM and makes the rig's
memory use predictable. `VOICERIG_DIARIZATION_DEVICE=cuda` is an explicit opt-in,
not an automatic optimization.
