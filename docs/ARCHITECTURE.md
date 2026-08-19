# Architecture

```text
Audio / Video
    |
    v
FFmpeg decode -> canonical mono PCM16 WAV @ 24 kHz
    |
    v
.venv-diarization / pyannote 4.0.7 (CPU subprocess)
    |   - WAV decoded by Python stdlib
    |   - in-memory waveform dict -> pyannote
    |   - no TorchCodec file-decoder on critical path
    |
    v
Cross-file speaker clustering
    |
    +-> clear dominant speaker -> automatic
    |
    +-> ambiguous -> playable speaker samples -> one user choice
    |
    v
Reference ranking / stitching
    |
    v
.venv / Chatterbox Multilingual V3 (CUDA)
    |                |
    |                +-> preview.wav (PCM16)
    +-> conditioning.pt
    |
    v
.mrvoice package
    |
    +-> primary + backup references
    +-> revision-aware conditioning
    +-> ~/.kaliv/voices/ (atomic same-host install)
    |
    v
VoiceRig loopback sidecar :8765
    |
    v
ModelRig worker provider facade
    |
    v
ModelRig authenticated backend :8080
```

Normal-UI'et eksponerer med vilje ingen model-, sample-rate-, embedding- eller
TTS-knapper. Den eneste ekstra interaktion er speaker-valg, når systemet faktisk
ikke kan vælge personen sikkert selv.

## To isolerede Python-miljøer

### Hovedruntime — `.venv`

- Python 3.11
- VoiceRig/FastAPI
- Chatterbox Multilingual V3 fra den verificerede source-revision angivet i
  `voicerig/model_contract.py`
- Torch 2.6.0 + Torchaudio 2.6.0 med CUDA 12.6

VoiceRig bruger ikke PyPI-versionen som V3-identitet. Source-revisionen er en del
af både dependency-kontrakten og nye `.mrvoice`-manifesters engine metadata.

### Speaker-runtime — `.venv-diarization`

- Python 3.11
- pyannote.audio 4.0.7
- Torch 2.8.0 CPU
- Torchaudio 2.8.0 CPU
- TorchCodec 0.7.0
- `pyannote/speaker-diarization-community-1`

Den runtime er CPU-only ved installation, warmup og fysisk preflight. Det løser
både dependency-konflikten med Chatterbox og beskytter 12 GB GPU-budgettet.

## Hvorfor TorchCodec ikke decoder VoiceRig-lyd

pyannote 4.0.7 har TorchCodec som dependency og bruger det normalt til file IO.
VoiceRig har imidlertid allerede en kontrolleret mediepipeline og konverterer
alle kilder til canonical mono PCM16 WAV.

Worker-processen læser derfor denne WAV direkte med Python-standardbiblioteket,
laver en float waveform tensor og kalder pyannote med:

```python
{
    "waveform": waveform,   # shape: channel x time
    "sample_rate": 24000,
    "uri": "source_00"
}
```

Det gør Windows-diarization uafhængig af TorchCodecs FFmpeg-DLL discovery. Den
pinnede TorchCodec-version bevares, fordi den er del af pyannotes dependency-
kontrakt, men VoiceRig behøver ikke dens file decoder til egne normalized inputs.

## Model warmup som installationskontrakt

`setup-windows.ps1` stopper ikke ved `pip install`. Det loader begge stacks:

1. Chatterbox V3 downloades og indlæses på CUDA; dansk support verificeres.
2. pyannote community-1 downloades og indlæses i CPU-runtime.
3. package-/Torch-versioner og CPU-only status verificeres.
4. in-memory PCM-input-protokollen registreres.
5. `voicerig-data/model-readiness.json` skrives atomisk.

UI/readiness accepterer kun en marker, der matcher den **aktuelle** modelkontrakt.
En kode-/modelkontrakt-opgradering gør derfor en gammel marker stale og kræver
setup/warmup igen i stedet for at skabe en skjult first-use migration.

## Speakeridentitet

Diarization køres én gang pr. build for alle uploaded clips i samme CPU-worker.
Speaker-embeddings matches på tværs af filer via varighedsvægtede centroids.
Det undgår single-link chaining, hvor A~B og B~C ellers fejlagtigt kan samle A
og C.

Ved klar dominans vælges personen automatisk. Ved reel tvivl returnerer backend
op til fire korte PCM16-prøver før Chatterbox overhovedet loades. Brugerens valg
bindes til et konkret input-index + timestamp inde i et taleturn, så genanalysen
genfinder personen ud fra materialet i stedet for et ustabilt rangnummer.

## Reference- og package-lag

Referencevælgeren kan bruge ét langt rent turn eller stitch flere korte turns fra
samme speaker. Kildehullerne kopieres ikke; kun små syntetiske stilhedsgaps
indsættes.

`.mrvoice` indeholder:

- primær `reference.wav`
- `conditioning.pt`
- `preview.wav`
- manifest + SHA-256 checksums
- normalt op til tre diverse backup-references

`conditioning.pt` er en performance-optimering. `reference.wav` er autoritativ.
Runtime indlæser kun serialiseret conditioning direkte ved matchende Chatterbox
source-revision; ellers regenereres den fra referenceaudio.

## GPU/VRAM invariant

VoiceRig v1 målretter en enkelt 12 GB NVIDIA-GPU:

- Chatterbox ejer CUDA.
- pyannote er CPU-only.
- Kun ét voice-build kan køre ad gangen.
- Build og sidecar-TTS deler samme cached Chatterbox-model.
- Conditioning + preview holdes atomisk under samme re-entrant GPU-lås.
- Peak CUDA allocated/reserved måles i **VoiceRig-serverprocessen**, ikke i en
  separat validatorproces.

Den fysiske validator nulstiller peak-statistik via det rigtige build-flow og
læser peak efter både build og efterfølgende TTS fra den samme serverproces.

## ModelRig-grænse

VoiceRig og ModelRig deler ikke Chatterbox-modelinstanser inde i ModelRig-
workeren. ModelRig har et provider-lag:

```text
auto -> VoiceRig/.mrvoice når sidecar er sund
     -> Piper fallback ellers
```

VoiceRig-sidecaren er loopback-only på `127.0.0.1:8765`. ModelRigs rå worker er
også intern/loopback. Klienter bruger ModelRigs autentificerede backend.

Final physical acceptance spørger derfor ikke workerens 8099-port direkte. Den
kalder:

```text
GET http://127.0.0.1:8080/api/v1/health/full
Authorization: Bearer <MODELRIG_TOKEN>
```

og kræver, at `checks.tts.provider == "voicerig"` samt at aktiv package matcher
den profil, acceptance netop byggede.
