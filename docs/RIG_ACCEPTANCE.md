# VoiceRig fysisk acceptance — RTX 3060 12 GB

Denne runbook er den sidste gate før VoiceRig MVP PR #1 må gøres ready/merge.
Den skal køres på den faktiske Windows-rig med NVIDIA RTX 3060 12 GB og et eller
flere rigtige lyd-/videoklip med den stemme, der skal clones.

## 1. Hent den eksakte kandidat

```powershell
cd C:\Users\admin\Desktop\VoiceRig
git fetch origin
git switch agent/voicerig-mvp
git pull --ff-only origin agent/voicerig-mvp
git status --short
git rev-parse HEAD
```

`git status --short` skal være tom. Notér HEAD i `validation-report.json`-noter,
hvis acceptance-resultatet senere kopieres til PR'en.

## 2. Installation / opdatering

```powershell
.\setup-windows.ps1
```

Krav:

- hovedmiljøet finder CUDA
- GPU-navn og VRAM printes
- Chatterbox-miljø bruger CUDA-enabled Torch 2.6.0
- separat diarization-miljø er CPU-only
- setup afslutter uden exception

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
- separat diarization-Python kan importere `pyannote.audio`
- diarization-Torch rapporterer ingen CUDA

Resultatet skrives til:

```text
validation-report.json
```

## 4. Fuld voice-build

Brug helst 2–3 naturlige klip, så både cross-file speaker matching og automatisk
referenceudvælgelse bliver testet.

```powershell
.\validate-rig.ps1 `
  -Source "C:\testdata\voice-01.mp4","C:\testdata\voice-02.m4a" `
  -Name "VoiceRig Acceptance"
```

Krav til PASS:

- pyannote diarization bruges faktisk
- ingen ambiguity-fejl for den tilsigtede person
- `.mrvoice` oprettes og valideres
- `reference.wav` oprettes
- Chatterbox conditioning oprettes
- preview genereres som PCM16 WAV
- profilen installeres i `~/.kaliv/voices/`
- testsyntese oprettes som PCM16 `*-validation.wav`
- reference/preview/testsyntese passerer automatisk WAV-, varigheds- og audible-gate
- ingen CUDA OOM
- peak allocated/reserved VRAM registreres i rapporten
- reference og testsyntese køres gennem pyannote igen for at rapportere speaker-embedding cosine

`speaker_similarity.cosine` er **kun en måling** i MVP'en. Der er bevidst ingen
hård tærskel endnu; den skal kalibreres mod rigtige danske reference/syntese-par,
før den må påvirke PASS/FAIL.

Artifacts ligger i:

```text
validation-output\
validation-report.json
```

## 5. Lyttekontrol

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

## 6. ModelRig end-to-end

Start den aktuelle ModelRig `main` på riggen og kør derefter:

```powershell
.\validate-rig.ps1 `
  -Source "C:\testdata\voice-01.mp4","C:\testdata\voice-02.m4a" `
  -Name "VoiceRig Acceptance" `
  -RequireModelRig
```

Krav:

- `http://127.0.0.1:8099/capabilities` svarer
- `tts=true`
- VoiceRig-sidecaren er tilgængelig lokalt
- ModelRig kan syntetisere via den installerede `.mrvoice`
- Piper fallback er fortsat tilgængelig, hvis VoiceRig-sidecaren stoppes

## 7. Acceptance-record

Følgende værdier kopieres fra `validation-report.json` til PR #1:

- commit SHA
- GPU-navn
- total/fri VRAM før build
- peak allocated VRAM
- peak reserved VRAM
- buildtid
- syntesetid
- `diarization_used`
- `speaker_similarity.cosine` (informational, threshold = none)
- syntese-WAV sample rate/duration/RMS
- ModelRig `tts` capability
- manuel lydvurdering: PASS / QUALITY FAIL

## Definition of Done

PR #1 må først gøres ready og merges, når:

1. GitHub CI er grøn på samme commit som den fysiske kandidat.
2. Preflight er PASS.
3. Fuld voice-build er PASS.
4. Peak VRAM holder sig inden for RTX 3060 12 GB uden OOM.
5. Manuel lyttekontrol er PASS.
6. ModelRig end-to-end er PASS.

Hvis ét punkt fejler, beholdes PR'en som draft og fejlen rettes på samme branch.
