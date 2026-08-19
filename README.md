# VoiceRig

VoiceRig laver en portabel ModelRig-stemmeprofil ud fra almindelige lyd- og videoklip.

**Målet er ét simpelt flow:** vælg filer → giv stemmen et navn → få en `.mrvoice` og installér den direkte i ModelRig.

## MVP

- Læser lyd/video gennem FFmpeg.
- Finder et godt referenceklip automatisk.
- Kan bruge lokal `pyannote/speaker-diarization-community-1` til flere talere.
- Bygger Chatterbox Multilingual V3 voice conditioning.
- Genererer dansk preview.
- Pakker `reference.wav`, `conditioning.pt`, `preview.wav`, manifest og checksums i `.mrvoice`.
- Forsøger automatisk installation gennem ModelRig-backendens `/api/v1/voices/import`.
- Fungerer som local-first; kildefiler sendes ikke til en cloudtjeneste af VoiceRig.

## Krav

- Python 3.11+
- FFmpeg på `PATH`
- Til fuld voice-cloning: CUDA anbefales, men Chatterbox vælger CPU fallback hvis CUDA ikke findes.

## Installation

På Windows:

```powershell
.\setup-windows.ps1
.\start-windows.ps1
```

Manuelt:

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[voice]"
```

`pyannote` community-1 kræver ved første model-download, at modelvilkårene accepteres og at `HF_TOKEN` er sat. Når modellerne ligger lokalt, kører selve diarization lokalt.

## Start

```bash
voicerig
```

Åbn derefter `http://127.0.0.1:8765`.

## ModelRig

Standardadresse er `http://127.0.0.1:8080`. Den kan ændres med:

```bash
MODELRIG_BASE_URL=http://127.0.0.1:8080
```

ModelRig skal implementere `POST /api/v1/voices/import` for direkte installation. ModelRigs nuværende arkitektur bruger Go-backenden på port 8080 og bearer-auth; `MODELRIG_TOKEN` kan derfor sættes, når import-endpointet tilføjes. Indtil da kan `.mrvoice` downloades manuelt fra VoiceRig.

## Status

Dette er første implementerede MVP-skelet. `.mrvoice`-pakning og reference-selection har automatiske tests. Fuld end-to-end voice generation kræver de tunge ML-modeller og skal hardwarevalideres på den rigtige rig.
