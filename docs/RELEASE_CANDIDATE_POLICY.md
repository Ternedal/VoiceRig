# VoiceRig release-candidate policy

VoiceRig physical and cross-product acceptance refs are forensic release evidence.

## Immutable refs

- A `release/voicerig-v1-physical-rcN` ref is never moved after it has been used for physical evidence.
- A `release/voicerig-v1-e2e-rcN` ref is never moved after it has been used for cross-product evidence.
- Any code or test change after a pinned candidate requires a new RC number.
- CI evidence from one SHA must never be presented as evidence for another SHA.
- Physical evidence from one SHA must never be presented as evidence for another SHA.
- Source audio, generated WAV files, `.mrvoice` packages and tokens are not stored as GitHub release evidence.

## Accepted V1 pins

### VoiceRig

- Ref: `release/voicerig-v1-physical-rc25`
- SHA: `587e6cced8bde599a0f62d8bd181d9d9a45f5469`
- Physical gate: issue #18 — PASS / completed
- Final ModelRig E2E gate: issue #19 — PASS / completed

### ModelRig E2E

- Ref: `release/voicerig-v1-e2e-rc12`
- SHA: `feec69a79488aa95d9cb8c036882d21a38122c43`
- Final cross-product gate: issue #19 — PASS / completed

## V1 candidate history retained for forensic use

The accepted RC25 ref is the authoritative VoiceRig V1 product pin. Older refs remain historical evidence and must not be rewritten merely to simplify the branch list.

Known late-stage history:

| Candidate | Status | Reason / evidence |
| --- | --- | --- |
| RC12 | FAIL | blank `HF_TOKEN=` produced an invalid authorization header |
| RC13 | FAIL | PowerShell 5.1 stderr handling caused terminating `NativeCommandError` |
| RC14 | SUPERSEDED | physical install/readiness passed; Danish voice quality failed |
| RC15 | SUPERSEDED | Danish tuning remained insufficient |
| RC16 | SUPERSEDED | multi-file/reference limitations discovered |
| RC17 | SUPERSEDED | additive selection and cross-file pooling completed |
| RC18 | SUPERSEDED | pre-physical VRAM eviction risk found |
| RC19 | SUPERSEDED | VRAM-safe Røst comparison candidate |
| RC20 | SUPERSEDED | OmniVoice source identity was not pinned strongly enough |
| RC21 | FAIL | OmniVoice worker import shadowing on Windows |
| RC22 | PASS / decision candidate | physical A/B/C proved Røst and OmniVoice viable; Røst led Danishness |
| RC23 | PASS / decision candidate | Røst reference 3 won physical likeness comparison |
| RC24 | SUPERSEDED | package-runtime candidate superseded by production-default + locale/accent SHA |
| RC25 | PASS / ACCEPTED | final VoiceRig V1 physical and ModelRig E2E acceptance |

## Archive policy

Do not delete historical RC refs merely for tidiness. If branch clutter becomes a real maintenance problem, first preserve a machine-readable mapping of ref -> SHA -> status -> evidence issue, then archive by creating immutable tags or another documented mechanism. Never repoint an existing accepted or failed RC ref.

## Post-V1 development

Post-V1 work starts from `main` after the accepted V1 merge and uses normal feature branches. It does not modify RC25 and must not be described as part of the V1 physical acceptance unless a new release candidate is explicitly created and accepted.
