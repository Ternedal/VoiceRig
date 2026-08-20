# VoiceRig

VoiceRig er et lokalt Windows-system til at lave portable ModelRig-stemmeprofiler ud fra almindelige lyd- og videoklip.

**Produktflowet er bevidst enkelt:** vælg 1–10 klip → giv stemmen et navn → VoiceRig finder den rigtige speaker, bygger stemmen og installerer en `.mrvoice` direkte i ModelRig.

## VoiceRig V1

V1 indeholder hele den daglige produktvej:

- lyd/video-ingest gennem FFmpeg,
- lokal `pyannote/speaker-diarization-community-1` til flere talere,
- cross-file speaker matching og automatisk valg ved tydelig dominans,
- afspilleligt speaker-valg ved reel tvivl,
- kvalitetssortering og stitching af rene taleturns,
- Chatterbox Multilingual V3 med dansk som standard,
- portabel `.mrvoice` med checksums, reference, conditioning og preview,
- automatisk lokal ModelRig-installation,
- stemmebibliotek med preview, aktiv/default, import, eksport og sikker sletning,
- **Test stemme** med vilkårlig tekst direkte i VoiceRig uden at ændre ModelRig-default,
- persistente voice-build jobs med progress, cancel og resume efter browser-refresh,
- lokal TTS-sidecar til ModelRig,
- Piper fallback i ModelRig,
- secret-safe ModelRig-tokenkonfiguration direkte fra System-fanen,
- diagnostics og support-ZIP uden kildeaudio, profiler eller tokens,
- stabil per-user storage, retention og cleanup,
- Windows install/update/rollback/uninstall,
- loopback-only sikkerhedsgrænse som produktdefault.

VoiceRig er local-first. Kildeklip sendes ikke til cloud af VoiceRig.

## Hardwaremål

VoiceRig V1 målretter Windows 10/11 med én NVIDIA-GPU i **12 GB-klassen**, herunder RTX 3060 12 GB.

Runtime er bevidst delt:

- `.venv`: VoiceRig + verificeret Chatterbox Multilingual V3 source-revision + Torch/Torchaudio 2.6.0 CUDA 12.6.
- `.venv-diarization`: pyannote.audio 4.0.7 + Torch 2.8.0 + Torchaudio 2.8.0 + TorchCodec 0.7.0, CPU-only.

Speaker-analyse bruger dermed ikke GPU-VRAM, som reserveres til Chatterbox. VoiceRig normaliserer input til mono PCM16 WAV og sender waveformen in-memory til pyannote.

## Installation på Windows

Den normale produktinstallation er:

```powershell
.\install-windows.ps1
```

Installeren:

1. finder eller installerer Git, FFmpeg og Python 3.11 via winget,
2. opretter de isolerede VoiceRig- og diarization-runtimes,
3. installerer den verificerede CUDA/Chatterbox- og CPU/pyannote-stack,
4. henter og verificerer modellerne,
5. håndterer første Hugging Face-adgang interaktivt hvis pyannote kræver den,
6. skriver model-readiness i den stabile per-user datamappe,
7. sætter per-user autostart,
8. starter og verificerer den lokale service,
9. åbner VoiceRig i browseren.

`setup-windows.ps1` er den lavere niveau setup/acceptance-vej. Almindelige installationer bør bruge `install-windows.ps1`.

### Første pyannote-download

`community-1` er en gated Hugging Face-model. Hvis warmup mangler adgang, åbner installeren model-siden og beder om et read-token **med skjult input**. Tokenet gemmes kun i repoets lokale `.env`; det sendes ikke til VoiceRigs supportpakke.

Hvis modellen allerede er tilgængelig/cachet, spørger installeren ikke om et token.

`PYANNOTE_METRICS_ENABLED=0` er produktdefault.

## Data og privatliv

Uden en eksplicit `VOICERIG_DATA_DIR` bruger VoiceRig en stabil per-user placering:

```text
%LOCALAPPDATA%\VoiceRig
```

Ældre installationer, hvor `.env` indeholder `VOICERIG_DATA_DIR=voicerig-data`, migreres automatisk til den stabile placering. En reel brugerdefineret path respekteres stadig.

Færdig jobhistorik er bounded, og pauserede speaker-jobs udløber, så private kildeklip ikke ligger uendeligt. Support-ZIP indeholder kun systemmetadata og redigerede logs — aldrig kildeklip, WAV-filer, `.mrvoice`-profiler eller tokens.

## Brug

Start/åbn VoiceRig med:

```powershell
.\start-windows.ps1
```

UI kører på `http://127.0.0.1:8765` og er loopback-only som standard.

**Opret stemme** er først aktiv, når hardware- og model-readiness er grøn. Ved flerspeaker-tvivl vises korte afspillelige prøver; brugerens valg bindes til et konkret taleturn, hvorefter buildet fortsætter automatisk.

I **Mine stemmer** kan profiler previewes, importeres, eksporteres, aktiveres i ModelRig, slettes og testes med egen tekst.

I **System** vises runtime/GPU/model/ModelRig-status, repair-flow, secret-safe ModelRig device-token-konfiguration samt download af privacy-redigeret supportpakke. Tokenværdien returneres aldrig fra VoiceRigs config-API; UI'et kan kun se, om et token er konfigureret.

## `.mrvoice`

`.mrvoice` er en data-only ZIP-container. En profil indeholder mindst:

- `manifest.json`
- `checksums.json`
- `reference.wav`
- `conditioning.pt`
- `preview.wav`

og kan indeholde dokumenterede backup-references.

Profiler registrerer den eksakte Chatterbox source-revision. Hvis en senere VoiceRig-version bruger en anden revision, genbruges gammel serialized conditioning ikke blindt; den regenereres fra `reference.wav`.

Se `docs/MRVOICE_SPEC.md`.

## ModelRig

På samme maskine installeres `.mrvoice` atomisk i ModelRigs voice-mappe og kan markeres default. ModelRig kan bruge VoiceRigs sidecar på `127.0.0.1:8765` uden at loade en ekstra Chatterbox-model i sin worker-VRAM.

ModelRig beholder Piper som fallback, når VoiceRig ikke er tilgængelig i `auto`-provider-flowet.

Hvis ModelRigs backend kræver et parret device-token, kan det gemmes fra **System → ModelRig authentication**. Tokenet skrives lokalt til VoiceRigs `.env`, slår igennem i den kørende proces med det samme og sendes aldrig tilbage til browseren efter gem.

## Update og recovery

Opdatér en eksisterende checkout med:

```powershell
.\update-windows.ps1
```

Updateren installerer og verificerer den nye revision og ruller tilbage til den tidligere fungerende HEAD, hvis den nye service ikke kan installeres/starte korrekt.

Afinstallation:

```powershell
.\uninstall-windows.ps1
```

Brugerdata og profiler bevares som udgangspunkt. Lokale `HF_TOKEN`/`MODELRIG_TOKEN`-værdier ryddes fra VoiceRigs `.env` som sikker standard. Hvis de bevidst skal bevares til en senere geninstallation:

```powershell
.\uninstall-windows.ps1 -KeepSecrets
```

Slet også brugerdata og profiler eksplicit med:

```powershell
.\uninstall-windows.ps1 -RemoveData
```

`-RemoveData` spørger VoiceRigs egen config om den autoritative datamappe **før** runtime fjernes, så også en brugerdefineret `VOICERIG_DATA_DIR` i `.env` rammes korrekt.

## Fysisk rig-validering

Preflight:

```powershell
.\validate-rig.ps1
```

Fuld produkt-E2E med rigtige klip:

```powershell
.\validate-rig.ps1 `
  -Source "C:\klip\stemme1.mp4","C:\klip\stemme2.m4a" `
  -Name "VoiceRig Acceptance"
```

Den fulde validator bruger den kørende VoiceRig-service til både build og syntese og binder acceptance-rapporten til clean checkout + den kørende services source revision.

Med ModelRig som hård gate:

```powershell
$env:MODELRIG_TOKEN = "<parret device-token>"
.\validate-rig.ps1 `
  -Source "C:\klip\stemme1.mp4","C:\klip\stemme2.m4a" `
  -Name "VoiceRig Acceptance" `
  -RequireModelRig `
  -RequirePiperFallback
```

Efter manuel lyttekontrol afsluttes releasebeviset med:

```powershell
.\complete-acceptance.ps1 `
  -QualityPass `
  -QualityNote "Tydelig dansk, genkendelig stemme, ingen alvorlige artefakter"
```

Se `docs/RIG_ACCEPTANCE.md` og `docs/RELEASE_GATE.md`.

## Build og CI

VoiceRig-versionen har én kilde i `voicerig/__init__.py`. CI:

1. kører unit/regression-tests,
2. compile-checker Python,
3. syntax-checker browser-JavaScript med Node,
4. bygger wheel og sdist,
5. installerer wheel i en frisk runtime uden for source-træet,
6. starter den installerede VoiceRig-service på Linux og tester UI-assets/config/diagnostics over rigtig localhost HTTP,
7. bygger og installerer samme produktvej på Windows og tester service/UI/assets/diagnostics over localhost HTTP,
8. parser alle PowerShell-scripts.

Den aktuelle grønne PR-head og CI-run registreres i PR #1, ikke som et hårdkodet SHA i README.

## Release-status

PR #1 forbliver **draft**, indtil den færdige V1-head har bestået fysisk acceptance på RTX 3060 12 GB med rigtige klip, manuel stemmelighed/lydkvalitet, server-processens peak VRAM, ModelRig-provider og Piper fallback.
