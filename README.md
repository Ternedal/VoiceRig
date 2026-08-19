# VoiceRig

VoiceRig laver en portabel ModelRig-stemmeprofil ud fra almindelige lyd- og videoklip.

**Målet er ét simpelt flow:** vælg filer → giv stemmen et navn → få en `.mrvoice` og installér den direkte i ModelRig.

## MVP

- Læser lyd/video gennem FFmpeg.
- Finder et godt referenceklip automatisk.
- Bruger lokal `pyannote/speaker-diarization-community-1` til flere talere.
- Matcher samme speaker på tværs af flere klip.
- Bygger Chatterbox Multilingual V3 voice conditioning.
- Genererer dansk preview.
- Pakker `reference.wav`, `conditioning.pt`, `preview.wav`, manifest og checksums i `.mrvoice`.
- Installerer automatisk i den lokale ModelRig voice-mappe.
- Kører en lokal TTS-sidecar, som prebuilt ModelRig kan bruge direkte.
- Fungerer local-first; kildefiler sendes ikke til en cloudtjeneste af VoiceRig.

## Hardwaremål

VoiceRig er designet til en enkelt NVIDIA-GPU med 12 GB VRAM.

På Windows er runtime bevidst delt:

- `.venv`: VoiceRig + Chatterbox + PyTorch 2.6.0 med CUDA 12.6.
- `.venv-diarization`: pyannote + nyere CPU-only PyTorch.

Det er nødvendigt, fordi den aktuelle Chatterbox-version pinner PyTorch 2.6.0,
mens den aktuelle pyannote-version kræver PyTorch 2.8 eller nyere. Samtidig
sikrer splittet, at speaker-analyse ikke bruger GPU-VRAM.

## Krav

- Windows 10/11
- Python 3.11
- FFmpeg på `PATH`
- Git på `PATH`
- NVIDIA-GPU med fungerende driver til CUDA PyTorch

## Installation på Windows

Den understøttede installationsvej er:

```powershell
.\setup-windows.ps1
.\start-windows.ps1
```

`setup-windows.ps1` opretter begge isolerede Python-miljøer, installerer den
officielle CUDA-version af PyTorch til Chatterbox, installerer CPU-only
pyannote-runtime, verificerer at CUDA faktisk virker og sætter VoiceRig til
per-user autostart.

`pyannote` community-1 kræver ved første model-download, at modelvilkårene er
accepteret og at `HF_TOKEN` er sat. Når modellerne ligger lokalt, kører selve
analysen lokalt.

## Manuel udviklerinstallation

Hovedmiljø og diarization-miljø må **ikke** flettes sammen. Se
`docs/ARCHITECTURE.md` og `setup-windows.ps1` for den autoritative dependency-
opdeling. En simpel `pip install -e ".[voice,diarization]"` er bevidst ikke en
understøttet konfiguration.

## Start

```powershell
.\start-windows.ps1
```

UI åbner på `http://127.0.0.1:8765`.

## ModelRig

Når ModelRig er lokal, kopierer VoiceRig automatisk `.mrvoice` til
`~/.kaliv/voices/` og gør den til default. ModelRig behøver ikke være startet,
mens stemmen oprettes.

En prebuilt ModelRig-worker kan bruge VoiceRigs lokale TTS-sidecar på
`127.0.0.1:8765`; en Python-worker med Chatterbox installeret kan også bruge
`.mrvoice` in-process.

## Fysisk rig-validering

Efter installation kan miljøet kontrolleres uden at bygge en stemme:

```powershell
.\validate-rig.ps1
```

Preflight kontrollerer CUDA, GPU/VRAM, FFmpeg, Git, Chatterbox/torchaudio og den
separate CPU-runtime til speaker-analyse. Resultatet gemmes i
`validation-report.json`.

Den fulde accepttest bruger et eller flere rigtige lyd-/videoklip:

```powershell
.\validate-rig.ps1 -Source "C:\klip\stemme1.mp4","C:\klip\stemme2.m4a"
```

Den fulde test bygger en `.mrvoice`, kræver at speaker-diarization faktisk blev
brugt, installerer profilen lokalt, laver en dansk testsyntese og måler buildtid,
syntesetid samt peak allocated/reserved VRAM. Output gemmes i
`validation-output\`.

Hvis ModelRig-workeren også skal være en hård del af accepttesten:

```powershell
.\validate-rig.ps1 -Source "C:\klip\stemme1.mp4" -RequireModelRig
```

I den tilstand skal `http://127.0.0.1:8099/capabilities` være tilgængelig og
rapportere `tts=true`, ellers fejler valideringen.

## Status

MVP-koden og package-/sidecar-/Windows-kontrakter er dækket af CI. Den sidste
acceptgate er fysisk end-to-end validering med rigtige lyd-/videoklip på den
faktiske rig: modeldownload, voice creation, peak VRAM, genereringstid,
stemmelighed og ModelRig-afspilning.
