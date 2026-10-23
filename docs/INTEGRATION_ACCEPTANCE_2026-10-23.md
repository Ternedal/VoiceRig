# VoiceRig: integration acceptance checklist

Documentation update: 2026-10-23. This checklist is a validation plan, not a claim that checks passed.

## Responsibility and test focus

VoiceRig owns voice packages and synthesis; ModelRig owns authenticated orchestration and fallback. Distinguish local ASR, TTS and streamed conversation from real voice-cloning qualification. Test speaker selection, licensing, audio quality, GPU memory, Piper fallback and exact-head physical acceptance.

## Cross-system verification

- [ ] Identify the exact implementation commit and API/schema revision.
- [ ] Check setup, credentials, ports and local/network trust boundaries against source.
- [ ] Exercise both success and failure paths, including timeouts, restarts and rollback.
- [ ] Record real-device evidence separately from automated CI.
- [ ] Confirm that changes preserve ModelRig's authenticated policy and approval boundaries.
- [ ] Update release notes only after evidence and required checks pass.

See [Kaliv ecosystem map](KALIV_ECOSYSTEM.md) and [ModelRig system integration documentation](https://github.com/Ternedal/ModelRig/tree/main/docs). KalivNexus is a proposed integration, not an established runtime dependency.
