# VoiceRig fysisk acceptance — RTX 3060 12 GB

Denne runbook er den sidste gate før VoiceRig V1 PR #1 må gøres ready/merge.
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

Den autoritative immutable release-ref og dens eksakte SHA står i issue #3.
Checkout altid den ref, ikke en bevægelig udviklingsbranch:

```powershell
cd C:\Users\admin\Desktop\VoiceRig
git fetch origin
git checkout <release-ref-fra-issue-3>
git reset --hard <sha-fra-issue-3>
git status --short
git rev-parse HEAD
```

`git status --short` skal være tom. Acceptance-værktøjerne kontrollerer dette
igen maskinelt og nægter fysisk acceptance på et dirty checkout.

VoiceRig fryser service-identiteten **når processen starter**. Dermed kan en
ældre proces ikke se ud som ny kode, blot fordi Git HEAD ændres under den.
Den eksakte checkout-identitet skrives til `validation-report.json` som:

```text
source_evidence.checkout.revision
source_evidence.checkout.branch
source_evidence.checkout.dirty
source_evidence.checkout.root
source_evidence.service.source.revision
source_evidence.service.source.dirty
source_evidence.service.source.root
source_evidence.same_revision
source_evidence.same_root
```

Både `same_revision` og `same_root` skal være `true` i den fulde E2E.

## 2. Installation / opdatering

Den normale produktvej er:

```powershell
.\install-windows.ps1
```

Ved direkte acceptance/debug kan `setup-windows.ps1` køres, men normal fysisk
release skal bevise den samme brugerrettede installationsvej som produktet.
`-SkipModelWarmup` må ikke bruges til final acceptance.

Setup/installation skal bevise:

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
- aktiv service rapporterer samme startup revision **og checkout-root** som den installerede kandidat
- setup afslutter uden exception

Ved første pyannote-download åbner produktinstalleren den gatede community-1-side
og kan gemme et Hugging Face read-token lokalt i `.env`, uden at tokenet skrives
i kommandohistorikken.

Ved opdatering må en allerede kørende VoiceRig kun muteres, hvis den tilhører
den aktuelle checkout. Efter opdatering kræves samme clean root + ny Git HEAD.
Dermed må gammel kode i RAM ikke bestå acceptance efter et checkout-skift.

## 3. Preflight

```powershell
.\validate-rig.ps1
```

Krav til PASS:

- `VoiceRig rig-validation: PASS`
- checkout er clean
- checkout revision/root kan aflæses
- GPU er RTX 3060 eller den faktiske 12 GB target-GPU
- registreret VRAM er mindst 11 GiB
- Chatterbox device er `cuda`
- FFmpeg og Git er fundet
- `chatterbox.mtl_tts` og `torchaudio` kan importeres
- model-readiness marker matcher den nuværende VoiceRig-modelkontrakt
- separat diarization-Python kan importere pyannote/Torch/Torchaudio/TorchCodec
- diarization-runtime rapporterer ingen CUDA

Resultatet skrives til `validation-report.json`.

## 4. Start den rigtige VoiceRig-service

```powershell
.\start-windows.ps1
```

Fuld acceptance forventer den normale loopback-service på
`http://127.0.0.1:8765`.

Ved fuld E2E kalder acceptance-wrapperen `/api/readiness` **før** ML-arbejdet og
kræver:

- service svarer som VoiceRig
- service rapporterer startup Git source revision og checkout-root
- service startup-checkout var clean
- service revision er identisk med validatorens checkout
- service root er identisk med validatorens checkout-root

Hvis et punkt fejler, stopper acceptance på `stage=source-identity` før
voice-build.

## 5. Fuld produkt-E2E

Brug helst 2–3 naturlige klip, så både cross-file speaker matching og automatisk
referenceudvælgelse bliver testet.

```powershell
.\validate-rig.ps1 `
  -Source "C:\testdata\voice-01.mp4","C:\testdata\voice-02.m4a" `
  -Name "VoiceRig Acceptance"
```

Kørslen gør følgende over HTTP mod den rigtige VoiceRig-service:

1. beviser clean checkout + aktiv service fra samme root og startup Git HEAD
2. uploader mediefiler til `/api/voices`
3. kræver rigtig pyannote diarization
4. bygger og installerer `.mrvoice`
5. downloader pakken igen gennem `/api/packages/...`
6. validerer package/checksums
7. udtrækker og validerer `reference.wav`
8. syntetiserer dansk via `/api/tts/synthesize`
9. validerer den returnerede PCM16 WAV
10. aflæser peak VRAM fra den **samme serverproces**
11. kører reference + syntese gennem pyannote til en informativ similarity-måling

Hvis materialet er reelt tvetydigt og produktet returnerer speaker-picker, fejler
den automatiske acceptance med en tydelig besked. Flerspeaker-pickerens UI testes
manuelt separat; automatiseret benchmark bør bruge materiale, hvor målpersonen
kan identificeres entydigt.

Krav til PASS omfatter:

- `source_evidence.checkout.dirty == false`
- `source_evidence.service.source.dirty == false`
- `source_evidence.same_revision == true`
- `source_evidence.same_root == true`
- `diarization_used == true`
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

`speaker_similarity.cosine` er kun informationsmåling, indtil en tærskel er
kalibreret på rigtige danske reference/syntese-par.

## 6. Lyttekontrol

Afspil både reference- og validation-WAV fra `validation-output\`.

Manuel acceptance kræver:

- referencefilen indeholder kun den ønskede person
- ingen tydelig anden speaker er stitched ind
- syntesen er forståelig dansk
- stemmeidentiteten er genkendelig som kilden
- ingen alvorlig metallisk forvrængning, gentagelsesloop eller hallucineret tale

Hvis stemmen er teknisk korrekt men ligheden er utilstrækkelig, registreres det
som **QUALITY FAIL**, ikke som software-PASS.

## 7. ModelRig + automatisk Piper fallback

Sæt det parrede ModelRig-device-token i den aktuelle PowerShell-session og kør:

```powershell
.\validate-rig.ps1 `
  -Source "C:\testdata\voice-01.mp4","C:\testdata\voice-02.m4a" `
  -Name "VoiceRig Acceptance" `
  -RequireModelRig `
  -RequirePiperFallback
```

ModelRig-providerbeviset kommer fra den autentificerede backend på port 8080.
Den lokale worker bruges kun til den målrettede Piper-syntese på loopback.

Fallback-testen failer closed og kræver hele kæden:

1. aktiv VoiceRig matcher clean checkout **root + startup SHA**
2. kun den verificerede VoiceRig og dens lokale launcher stoppes
3. ModelRig skifter til `provider == "piper"`
4. worker producerer en rigtig RIFF/WAV
5. VoiceRig genstartes i `finally`
6. genstartet VoiceRig matcher samme root + SHA og er clean
7. ModelRig vender tilbage til `provider == "voicerig"` med samme package

`piper-fallback-report.json` indeholder bl.a.:

```text
checkout_revision
checkout_root
stopped_voicerig_pid
fallback.provider
piper_synthesis.provider
piper_synthesis.output
piper_synthesis.riff
restarted_service_pid
restarted_service_revision
restarted_service_root
restored.provider
```

## 8. Slutbevis

Efter lyttekontrollen:

```powershell
.\complete-acceptance.ps1 `
  -QualityPass `
  -QualityNote "Tydelig dansk, genkendelig stemme, acceptabel prosodi, ingen alvorlige artefakter"
```

`release-acceptance.json` skal have `ok: true`. Final-gaten genvaliderer både
revision, checkout-root, artifacts, ModelRig/Piper-kæde og manuel kvalitetsnote.

Upload aldrig rå lyd, genereret WAV, `.mrvoice` eller tokens til GitHub; kun
metadata, hashes og verdicts.

## Definition of Done

PR #1 må først gøres ready og merges, når:

1. alle autoritative GitHub Actions-workflows er grønne på samme pinned VoiceRig commit,
2. fysisk checkout er clean og matcher pinned release-ref,
3. aktiv VoiceRig-service er clean og matcher samme startup revision **og root**,
4. produktinstallation + model-warmup er PASS,
5. preflight er PASS,
6. fuld HTTP-baseret VoiceRig product-E2E er PASS,
7. peak VRAM holder sig inden for RTX 3060 12 GB uden OOM,
8. manuel lyttekontrol er PASS,
9. ModelRig backend rapporterer VoiceRig med korrekt package,
10. Piper fallback producerer en rigtig WAV og restore til samme VoiceRig root/SHA er PASS,
11. `release-acceptance.json` er `ok: true`,
12. der ikke er nye review-blockers.

Hvis ét punkt fejler, beholdes PR'en som draft. Hvis kode eller release-ref ændres,
er tidligere fysisk evidence stale og skal køres igen.
