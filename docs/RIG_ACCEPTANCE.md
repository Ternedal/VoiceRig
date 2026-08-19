# VoiceRig fysisk acceptance — RTX 3060 12 GB

Denne runbook er den sidste gate før VoiceRig MVP PR #1 må gøres ready/merge.
Den skal køres på den faktiske Windows-rig med NVIDIA RTX 3060 12 GB og et eller
flere rigtige lyd-/videoklip med den stemme, der skal clones.

Den fulde test går gennem **de samme processer og HTTP-flader som produktet**:

```text
validation script
   │
   ├──> VoiceRig :8765 /api/voices
   │       └── Chatterbox V3 på CUDA + pyannote CPU
   │
   ├──> VoiceRig :8765 /api/tts/synthesize
   │       └── samme langlivede Chatterbox-model
   │
   └──> ModelRig backend :8080 /api/v1/health/full
           └── checks.tts.provider == "voicerig"
```

Validatoren loader derfor **ikke** sin egen Chatterbox-model. Peak VRAM kommer
fra den rigtige VoiceRig-serverproces, så 12 GB-målingen ikke forvrænges af en
anden CUDA-model i validatorprocessen.

## 1. Hent den eksakte kandidat

```powershell
cd C:\Users\admin\Desktop\VoiceRig
git fetch origin
git switch agent/voicerig-mvp
git pull --ff-only origin agent/voicerig-mvp
git status --short
git rev-parse HEAD
```

`git status --short` skal være tom. Notér HEAD sammen med acceptance-resultatet,
så den fysiske PASS kan bindes til den samme commit som GitHub CI.

## 2. Installation / opdatering

```powershell
.\setup-windows.ps1
```

Normal setup må **ikke** bruge `-SkipModelWarmup` til acceptance.

Setup skal bevise:

- Python 3.11
- FFmpeg og Git
- CUDA-enabled Torch 2.6.0 i hovedmiljøet
- den verificerede Chatterbox V3 source-revision
- dansk (`da`) findes i den indlæste Chatterbox V3
- separat CPU-only diarization-miljø
- pyannote.audio 4.0.7
- Torch 2.8.0 CPU
- Torchaudio 2.8.0 CPU
- TorchCodec 0.7.0
- `pyannote/speaker-diarization-community-1` kan faktisk downloades/åbnes
- model-warmup skriver en gyldig `model-readiness.json`
- setup afslutter uden exception

Ved første pyannote-download skal community-1-vilkårene være accepteret på
Hugging Face, og et læse-token kan sættes som `HF_TOKEN` i repoets `.env`.
VoiceRig loader `.env` selv; eksisterende Windows/session-env vinder over filen.

## 3. Preflight

```powershell
.\validate-rig.ps1
```

Krav til PASS:

- `VoiceRig rig-validation: PASS`
- GPU er RTX 3060 eller den faktiske 12 GB target-GPU
- registreret VRAM er mindst 11 GiB
- Chatterbox device er `cuda`
- FFmpeg og Git er fundet
- `chatterbox.mtl_tts` og `torchaudio` kan importeres
- model-readiness marker matcher den nuværende VoiceRig-modelkontrakt
- separat diarization-Python kan importere pyannote/Torch/Torchaudio/TorchCodec
- diarization-runtime rapporterer ingen CUDA

Resultatet skrives til:

```text
validation-report.json
```

## 4. Start den rigtige VoiceRig-service

```powershell
.\start-windows.ps1
```

Fuld acceptance forventer den normale loopback-service på:

```text
http://127.0.0.1:8765
```

Validatoren kalder `/api/readiness` og stopper, hvis service-processens egen
readiness ikke er grøn.

## 5. Fuld produkt-E2E

Brug helst 2–3 naturlige klip, så både cross-file speaker matching og automatisk
referenceudvælgelse bliver testet.

```powershell
.\validate-rig.ps1 `
  -Source "C:\testdata\voice-01.mp4","C:\testdata\voice-02.m4a" `
  -Name "VoiceRig Acceptance"
```

Kørslen gør nu følgende over HTTP mod den rigtige VoiceRig-service:

1. uploader mediefiler til `/api/voices`
2. kræver rigtig pyannote diarization
3. bygger og installerer `.mrvoice`
4. downloader pakken igen gennem `/api/packages/...`
5. validerer package/checksums
6. udtrækker og validerer `reference.wav`
7. syntetiserer dansk via `/api/tts/synthesize`
8. validerer den returnerede PCM16 WAV
9. aflæser peak VRAM fra den **samme serverproces**
10. kører reference + syntese gennem pyannote til en informativ similarity-måling

Hvis materialet er reelt tvetydigt og produktet returnerer speaker-picker, fejler
den automatiske acceptance med en tydelig besked. Det er ikke et produktproblem:
flerspeaker-pickerens UI testes manuelt separat. Den automatiske benchmark bør
bruge materiale, hvor den tilsigtede person kan identificeres entydigt.

Krav til PASS:

- `diarization_used=true`
- `.mrvoice` oprettes, kan downloades og valideres
- `reference.wav` er gyldig og hørbar
- Chatterbox conditioning + preview lykkes
- profilen installeres i `~/.kaliv/voices/` og bliver default
- TTS-responsen siger `device=cuda`
- TTS-responsen siger præcis den netop byggede package
- testsyntese oprettes som PCM16 `*-validation.wav`
- ingen CUDA OOM
- server-processens peak allocated/reserved VRAM returneres
- reference og testsyntese giver om muligt speaker-embedding cosine

`speaker_similarity.cosine` er **kun en måling** i MVP'en. Der er bevidst ingen
hård tærskel endnu; den skal kalibreres mod rigtige danske reference/syntese-par,
før den må påvirke PASS/FAIL.

Artifacts ligger i:

```text
validation-output\
validation-report.json
```

## 6. Lyttekontrol

Afspil både:

```text
validation-output\*-reference.wav
validation-output\*-validation.wav
```

Manuel acceptance kræver:

- referencefilen indeholder kun den ønskede person
- ingen tydelig anden speaker er blevet stitched ind
- syntesen er forståelig dansk
- stemmeidentiteten er genkendelig som kilden
- ingen alvorlig metallisk forvrængning, gentagelsesloop eller hallucineret tale

Hvis stemmen er teknisk korrekt men ligheden er utilstrækkelig, registreres det
som **QUALITY FAIL**, ikke som software-PASS. Sammenhold den manuelle vurdering
med `speaker_similarity.cosine`; denne første måling bliver udgangspunktet for
senere kalibrering, ikke en efterrationaliseret tærskel.

## 7. ModelRig end-to-end gennem backend

Start den aktuelle ModelRig `main`, backend og worker som normalt. Final
integration testes **ikke** direkte mod worker-port 8099: workeren er intern og
loopback-only. Acceptance bruger ModelRigs autentificerede backend på port 8080.

Sæt token uden at skrive det ind i kommandohistorikken, fx i den aktuelle
PowerShell-session:

```powershell
$env:MODELRIG_TOKEN = "<dit parrede device-token>"
```

Kør derefter:

```powershell
.\validate-rig.ps1 `
  -Source "C:\testdata\voice-01.mp4","C:\testdata\voice-02.m4a" `
  -Name "VoiceRig Acceptance" `
  -RequireModelRig
```

Validatoren kalder:

```text
GET http://127.0.0.1:8080/api/v1/health/full
Authorization: Bearer <MODELRIG_TOKEN>
```

Krav til ModelRig PASS:

- backend kan kontaktes og Bearer-token accepteres
- `checks.tts.ok == true`
- `checks.tts.provider == "voicerig"`
- `checks.tts.package` er præcis den `.mrvoice`, acceptance netop byggede
- VoiceRig TTS-sidecaren er dermed den provider, ModelRig selv har valgt

Dette beviser den integrerede ModelRig-provider. Den separate Piper fallback-test
skal stadig udføres ved at stoppe VoiceRig-sidecaren og verificere ModelRigs
fallback-adfærd med den eksisterende Piper-stemme.

## 8. Acceptance-record

Følgende værdier kopieres fra `validation-report.json` til PR #1:

- commit SHA
- GPU-navn
- total/fri VRAM før build
- `gpu.after_build.peak_allocated_gb`
- `gpu.after_build.peak_reserved_gb`
- `gpu.after_synthesis.peak_allocated_gb`
- `gpu.after_synthesis.peak_reserved_gb`
- buildtid set fra HTTP-klienten
- syntesetid set fra HTTP-klienten
- `diarization_used`
- `speaker_similarity.cosine` (informational, threshold = none)
- syntese-WAV sample rate/duration/RMS
- ModelRig backend auth-status
- ModelRig TTS-provider
- ModelRig aktiv package
- manuel lydvurdering: PASS / QUALITY FAIL
- Piper fallback: PASS / FAIL

## Definition of Done

PR #1 må først gøres ready og merges, når:

1. GitHub CI er grøn på samme commit som den fysiske kandidat.
2. Setup model-warmup er PASS.
3. Preflight er PASS.
4. Fuld HTTP-baseret VoiceRig product-E2E er PASS.
5. Peak VRAM holder sig inden for RTX 3060 12 GB uden OOM.
6. Manuel lyttekontrol er PASS.
7. ModelRig backend rapporterer VoiceRig som aktiv TTS-provider med korrekt package.
8. Piper fallback er PASS.

Hvis ét punkt fejler, beholdes PR'en som draft og fejlen rettes på samme branch.
