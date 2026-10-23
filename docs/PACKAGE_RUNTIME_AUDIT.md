# Package and environment audit — VoiceRig

Source inspection: 2026-10-23; `pyproject.toml` on main. **No environment installed or tested.**

- Python **>=3.11**; Hatchling build; dynamic package version from `voicerig/__init__.py`.
- Base dependencies: FastAPI >=0.115, Uvicorn >=0.30, python-multipart >=0.0.9, python-dotenv >=1.0 and httpx >=0.27.
- `voice` extra pins Chatterbox source commit `5de7a54aa4e5e2baadb0182dde554908b48b85c2` rather than relying on an older PyPI distribution.
- `diarization` extra pins `pyannote.audio==4.0.7`; package comments explicitly require a **separate CPU-only environment/process** because its torch generation conflicts with Chatterbox.
- CLI: `voicerig = voicerig.app.main:run`.

## Operator checks

- [ ] Record exact VoiceRig revision and both environment dependency locks.
- [ ] Verify GPU TTS and CPU diarization remain isolated.
- [ ] Test real clips, speaker disambiguation, profile install and Piper fallback.
- [ ] Record latency, VRAM and exact-head acceptance before release claims.

See [architecture](ARCHITECTURE.md) and [integration acceptance](INTEGRATION_ACCEPTANCE_2026-10-23.md).
