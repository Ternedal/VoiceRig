# VoiceRig

VoiceRig laver en portabel ModelRig-stemmeprofil ud fra almindelige lyd- og videoklip.

**Målet er ét simpelt flow:** vælg filer → giv stemmen et navn → få en `.mrvoice` og installér den direkte i ModelRig.

## MVP

- Læser lyd/video gennem FFmpeg.
- Finder gode referenceklip automatisk og kan stitch flere rene taleturns uden at kopiere lyd fra hullerne mellem dem.
- Bruger lokal `pyannote/speaker-diarization-community-1` til flere talere.
- Matcher samme speaker på tværs af flere klip via varighedsvægtede speaker-centroids.
- Vælger automatisk ved tydelig dominans. Ved reel tvivl vises op til fire afspillelige stemmeprøver med **Brug denne stemme**.
- Fejler lukket hvis speaker-analysen ikke kan køre; undiarized fallback er kun en udvikler-escape hatch.
- Bygger Chatterbox Multilingual V3 conditioning og dansk preview.
- Pakker primær reference, conditioning, preview og op til tre diverse backup-references i `.mrvoice`.
- Installerer automatisk i den lokale ModelRig voice-mappe.
- Kører en lokal TTS-sidecar, som ModelRig kan bruge uden at loade en ekstra Chatterbox-model i workerens VRAM.
- Fungerer local-first; kildefiler sendes ikke til cloud af VoiceRig.

## Hardwaremål

VoiceRig v1 er målrettet en enkelt NVIDIA-GPU i **12 GB-klassen**, herunder RTX 3060 12 GB.

Windows-runtime er bevidst delt:

- `.venv`: VoiceRig + verificeret Chatterbox Multilingual V3 source-revision + Torch/Torchaudio 2.6.0 CUDA 12.6.
- `.venv-diarization`: pyannote.audio 4.0.7 + Torch 2.8.0 + Torchaudio 2.8.0 + TorchCodec 0.7.0, CPU-only.

Speaker-analyse bruger dermed ikke GPU-VRAM, som reserveres til Chatterbox. VoiceRig normaliserer selv input til mono PCM16 WAV og sender waveformen **in-memory** til pyannote. Det betyder, at TorchCodec er installeret som pyannote-dependency, men dens Windows file-decoder/FFmpeg-DLL discovery ikke ligger på den kritiske diarization-sti.

## Krav

- Windows 10/11
- Python 3.11
- FFmpeg på `PATH`
- Git på `PATH`
- NVIDIA-GPU med fungerende CUDA-driver

## Installation på Windows

```powershell
.\setup-windows.ps1
.\start-windows.ps1
```

`setup-windows.ps1`:

1. opretter begge isolerede Python-miljøer,
2. installerer den verificerede Chatterbox V3-kilde og CUDA-runtime,
3. installerer den eksakt pinnede CPU-only pyannote-stack,
4. opretter `.env` fra `.env.example` hvis nødvendigt,
5. downloader og **loader begge modeller som warmup**,
6. verificerer dansk V3, CPU-only diarization, runtime-versionerne og in-memory PCM-inputkontrakten,
7. skriver `voicerig-data/model-readiness.json`,
8. sætter per-user autostart.

Voice creation forbliver låst, indtil readiness-markeret matcher den aktuelle VoiceRig-modelkontrakt.

### Første pyannote-download

`community-1` kræver, at modellens vilkår accepteres på Hugging Face. Sæt derefter et read-token i repoets `.env`:

```text
HF_TOKEN=...
```

VoiceRig loader `.env` selv; eksisterende Windows/session-miljøvariabler vinder over filen.

`PYANNOTE_METRICS_ENABLED=0` er standard, så pyannote-telemetry er slået fra, medmindre den eksplicit aktiveres.

## Start

```powershell
.\start-windows.ps1
```

UI åbner på `http://127.0.0.1:8765`. **Opret stemme** aktiveres først, når lokal hardware- og model-readiness er grøn.

Normalflowet kræver kun filer + navn. Ved reel flerspeaker-tvivl vises korte prøver:

```text
Stemme 1   [▶]   [Brug denne stemme]
Stemme 2   [▶]   [Brug denne stemme]
```

Valget bindes til et konkret taleturn i materialet, hvorefter resten af buildet fortsætter automatisk.

## `.mrvoice`

Profiler er data-only ZIP-containere med `.mrvoice`-extension. Nye profiler registrerer den eksakte Chatterbox source-revision, der skabte `conditioning.pt`.

Hvis en senere VoiceRig-version bruger en anden Chatterbox-revision, genbruger runtime **ikke blindt** den gamle serialiserede conditioning. Den regenererer conditioning fra `reference.wav`, så profilen forbliver portabel.

Se `docs/MRVOICE_SPEC.md`.

## ModelRig

På samme maskine installeres `.mrvoice` atomisk i `~/.kaliv/voices/` og markeres som default. ModelRig behøver ikke være startet under selve voice-buildet.

ModelRig `main` kan derefter bruge VoiceRigs loopback-sidecar på `127.0.0.1:8765` og beholder Piper som fallback.

## Fysisk rig-validering

Preflight:

```powershell
.\validate-rig.ps1
```

Fuld produkt-E2E med rigtige klip:

```powershell
.\validate-rig.ps1 -Source "C:\klip\stemme1.mp4","C:\klip\stemme2.m4a"
```

Den fulde validator bruger den **kørende VoiceRig-service** til både build og syntese. Dermed måles peak VRAM i den samme langlivede Chatterbox-proces, som produktet faktisk bruger.

Hvis ModelRig-integration også skal være en hård gate, sæt et gyldigt parret device-token:

```powershell
$env:MODELRIG_TOKEN = "..."
.\validate-rig.ps1 -Source "C:\klip\stemme1.mp4" -RequireModelRig
```

Her spørges den autentificerede ModelRig-backend på `http://127.0.0.1:8080/api/v1/health/full`. PASS kræver bl.a. `checks.tts.provider == "voicerig"` og at ModelRig bruger den `.mrvoice`, testen netop byggede.

Fuld release-acceptance inklusive Piper fallback:

```powershell
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

Den komplette procedure og Definition of Done ligger i `docs/RIG_ACCEPTANCE.md` og `docs/RELEASE_GATE.md`.

## Build og distribution

VoiceRig-versionen har én kilde i `voicerig/__init__.py`. Hatch bruger samme version til wheel/sdist-metadata, og FastAPI/health rapporterer samme værdi.

GitHub Actions tester både editable udviklingsinstallationen og den **faktisk distribuerbare pakke**:

1. bygger wheel og sdist,
2. installerer wheel'en i en separat venv uden for source-træet,
3. kører `pip check`,
4. verificerer package-versionen mod `voicerig.__version__`,
5. verificerer at `voicerig/ui/index.html` findes i wheel'en,
6. verificerer at `voicerig`-CLI-entrypointet er installeret.

Det fanger packaging-fejl, som en editable installation ellers kan skjule.

## Status

Softwarekontrakterne er CI-dækkede. PR #1 forbliver draft, indtil den fysiske acceptance på RTX 3060 12 GB har bevist rigtig modeldownload, diarization, voice-build, server-processens peak VRAM, manuel stemmelighed/lydkvalitet, ModelRig-provider og Piper fallback.
