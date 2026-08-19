# VoiceRig v1 — kravspecifikation og acceptance

## Produktmål

Den normale bruger skal kun:

1. Trække 1–10 lyd- eller videofiler ind.
2. Give stemmen et navn.
3. Trykke **Opret stemme**.

Hvis én person tydeligt dominerer materialet, må VoiceRig ikke stille tekniske
spørgsmål. Hvis flere personer er omtrent lige tydelige, må den eneste ekstra
handling være at afspille korte stemmeprøver og vælge **Brug denne stemme**.

Resultatet er en portabel `.mrvoice`, som ModelRig kan bruge direkte.

## Input

V1 understøtter via FFmpeg:

```text
Video: MP4, MKV, MOV, AVI, WEBM, M4V
Audio: WAV, MP3, FLAC, M4A, AAC, OGG, OPUS, WMA
```

- Maks. 10 inputfiler pr. build.
- Samlet uploadbudget er konfigurerbart; default 2048 MB.
- Originale filer ændres aldrig.
- Midlertidige decode-/analysefiler ryddes automatisk.

## Automatisk speaker-pipeline

VoiceRig v1 skal:

- decode alle inputs til canonical mono PCM16 WAV
- køre pyannote community-1 lokalt
- holde pyannote i separat CPU-only runtime
- bruge exclusive diarization til rene taleturns når tilgængelig
- matche samme person på tværs af filer med speaker embeddings
- undgå single-link speaker-cluster chaining
- vælge hovedpersonen automatisk kun ved tydelig dominans
- ved tvivl vise op til fire afspillelige stemmeprøver
- genfinde et manuelt valg via inputfil + timestamp-anker, ikke kun rangnummer
- fejle lukket hvis speaker-analysen ikke kan køres sikkert

`VOICERIG_ALLOW_UNDIARIZED=1` er kun en udvikler-escape hatch til kendt
single-speaker-testmateriale og må ikke være normal produktadfærd.

## Referencevalg

- Primær reference skal indeholde mindst ca. 5.5 sekunders brugbar tale.
- Målet er ca. 6–10 sekunders ren tale.
- Flere korte taleturns fra samme person må stitches sammen.
- Lyd mellem valgte taleturns må ikke kopieres med, fordi en anden person kan tale der.
- Reference skal passere WAV-, varigheds- og audible/RMS-gate.
- `.mrvoice` må indeholde op til fem alternative references; VoiceRig v1 producerer normalt op til tre diverse backups.
- Backup-reference ranking skal begrænse overlap, så near-duplicates ikke fylder alle slots.

## TTS / GPU

Primær engine er Chatterbox Multilingual V3 med dansk som default.

Referencehardware for V1 er én NVIDIA-GPU i 12 GB-klassen:

- Chatterbox kører på CUDA.
- pyannote kører på CPU og må ikke bruge GPU-VRAM.
- kun ét voice-build må mutere Chatterbox-state ad gangen
- conditioning + preview skal være én atomisk GPU/model-state-transaktion
- preview skal genbruge allerede forberedt conditioning og må ikke beregne den igen
- TTS-sidecar og voice-build skal dele én conditioning-identitet, så cache og faktisk `model.conds` ikke kan divergere
- runtime skal måle peak allocated/reserved VRAM under fysisk acceptance

Preview og runtime-TTS skrives som deterministic signed PCM16 WAV.

## `.mrvoice` v1

Obligatorisk:

```text
manifest.json
checksums.json
reference.wav
conditioning.pt
preview.wav
```

Valgfrit:

```text
references/candidate_01.wav
...
references/candidate_05.wav
```

Pakken skal være data-only og valideres før brug:

- format/version
- manifest-schema og typer
- finite/range-validerede TTS-defaults
- exact payload/checksum-dækning
- SHA-256 mismatch
- path traversal
- backslash archive paths
- ukendte payloads
- dublerede entries
- krypterede entries
- entry count
- per-file og samlet uncompressed size

Se `docs/MRVOICE_SPEC.md` for den normative v1-kontrakt.

## ModelRig-integration

- `.mrvoice` installeres same-host atomisk i `~/.kaliv/voices/` og markeres som default.
- VoiceRig har en loopback-only TTS-sidecar på `127.0.0.1:8765`.
- ModelRig `main` understøtter VoiceRig-provider og `.mrvoice` via sidecaren.
- ModelRig beholder Piper som fallback.
- ModelRig må ikke loade en ekstra Chatterbox-model i sin worker-VRAM.
- VoiceRig kan stadig eksportere `.mrvoice`, selv hvis ModelRig ikke kører.

## Privacy

- VoiceRig er local-first.
- Kildeaudio/video, speaker embeddings og stemmeprofiler sendes ikke automatisk til cloud.
- Første download af pyannote-modellen kan kræve Hugging Face-token/modeladgang; selve analyseflowet kører derefter lokalt.

## Software acceptance

Følgende skal være dækket af GitHub CI:

- package/schema/security tests
- reference ranking/stitching tests
- diarization/clustering tests
- ambiguous-speaker selection + playable preview contract
- fail-closed speaker pipeline
- runtime/readiness tests
- PCM16/audio validation
- Chatterbox mutable-state/cache concurrency tests
- ModelRig client + TTS-sidecar tests
- rig-validation helper tests
- Python compileall
- PowerShell syntax

## Fysisk acceptance — sidste gate

PR #1 må forblive draft, indtil `docs/RIG_ACCEPTANCE.md` er gennemført på den
faktiske 12 GB-rig med rigtige klip.

Der skal dokumenteres:

- exact commit SHA
- setup/preflight PASS
- faktisk pyannote modeldownload/diarization
- `.mrvoice` build PASS
- peak VRAM uden CUDA OOM
- buildtid og syntesetid
- speaker-similarity cosine som informationsmåling
- manuel lyttekontrol PASS
- ModelRig `tts=true` og end-to-end afspilning PASS
- Piper fallback stadig funktionel

Ingen automatisk similarity-tærskel må opfindes før målingen er kalibreret på
rigtige reference/syntese-par.
