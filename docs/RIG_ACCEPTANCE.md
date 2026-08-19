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

`git status --short` skal være tom. `validate-rig.ps1` kontrollerer dette igen
maskinelt og nægter fysisk acceptance på et dirty checkout.

Den eksakte checkout-identitet skrives automatisk til:

```text
source_evidence.checkout.revision
source_evidence.checkout.branch
source_evidence.checkout.dirty
```

i `validation-report.json`. Der er derfor ikke længere et manuelt “notér HEAD”-
trin i acceptance-beviset.

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

Ved opdatering genstarter setup en allerede kørende VoiceRig-proces og kræver,
at den nye service rapporterer checkoutets aktuelle Git HEAD. Dermed må gammel
kode i RAM ikke bestå acceptance efter et `git pull`.

## 3. Preflight

```powershell
.\validate-rig.ps1
```

Krav til PASS:

- `VoiceRig rig-validation: PASS`
- checkout er clean
- checkout revision kan aflæses fra Git
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

Preflight-rapporten indeholder mindst checkout-identiteten under
`source_evidence.checkout`.

## 4. Start den rigtige VoiceRig-service

```powershell
.\start-windows.ps1
```

Fuld acceptance forventer den normale loopback-service på:

```text
http://127.0.0.1:8765
```

Ved fuld E2E kalder acceptance-wrapperen `/api/readiness` **før** ML-arbejdet og
kræver:

- service svarer
- service rapporterer Git source revision
- service checkout er clean
- service revision er identisk med det checkout, validatoren selv kører fra

Hvis et af disse punkter fejler, stopper acceptance på `stage=source-identity`
før voice-build. Rapporten indeholder:

```text
source_evidence.checkout
source_evidence.service.pid
source_evidence.service.source
source_evidence.same_revision
```

`source_evidence.same_revision` skal være `true` ved en gyldig fysisk E2E.

## 5. Fuld produkt-E2E

Brug helst 2–3 naturlige klip, så både cross-file speaker matching og automatisk
referenceudvælgelse bliver testet.

```powershell
.\validate-rig.ps1 `
  -Source "C:\testdata\voice-01.mp4","C:\testdata\voice-02.m4a" `
  -Name "VoiceRig Acceptance"
```

Kørslen gør følgende over HTTP mod den rigtige VoiceRig-service:

1. beviser clean checkout + aktiv service på samme Git HEAD
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
den automatiske acceptance med en tydelig besked. Det er ikke et produktproblem:
flerspeaker-pickerens UI testes manuelt separat. Den automatiske benchmark bør
bruge materiale, hvor den tilsigtede person kan identificeres entydigt.

Krav til PASS:

- `source_evidence.checkout.dirty == false`
- `source_evidence.service.source.dirty == false`
- `source_evidence.same_revision == true`
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

## 7. ModelRig + automatisk Piper fallback

Start den aktuelle ModelRig `main`, backend og worker som normalt. Final
integration testes ikke direkte mod worker-port 8099; ModelRig-providerbeviset
kommer fra den autentificerede backend på port 8080. Den lokale worker bruges
kun bagefter til den målrettede Piper-syntesetest, fordi backend ikke har en
separat ren TTS-route.

Sæt token uden at skrive det ind i kommandohistorikken, fx i den aktuelle
PowerShell-session:

```powershell
$env:MODELRIG_TOKEN = "<dit parrede device-token>"
```

Den endelige automatiske rig-kommando er:

```powershell
.\validate-rig.ps1 `
  -Source "C:\testdata\voice-01.mp4","C:\testdata\voice-02.m4a" `
  -Name "VoiceRig Acceptance" `
  -RequireModelRig `
  -RequirePiperFallback
```

Før fallback-delen kræver validatoren via ModelRig-backenden:

```text
GET http://127.0.0.1:8080/api/v1/health/full
Authorization: Bearer <MODELRIG_TOKEN>
```

Krav til VoiceRig-provider PASS:

- backend kan kontaktes og Bearer-token accepteres
- `checks.tts.ok == true`
- `checks.tts.provider == "voicerig"`
- `checks.tts.package` er præcis den `.mrvoice`, acceptance netop byggede

Når den del er grøn, kører `test-piper-fallback.ps1` automatisk og fail-closed:

1. identificerer den aktive VoiceRig-service via `/api/health`
2. kræver clean service-checkout på samme Git SHA som acceptance-checkoutet
3. stopper **kun** den verificerede VoiceRig-PID
4. venter på at ModelRig-backenden skifter til `checks.tts.provider == "piper"`
5. kalder ModelRig-worker **kun på loopback** `127.0.0.1:8099/voice/tts/synthesize`
6. kræver at worker-resultatet siger `provider == "piper"`
7. kræver at en rigtig RIFF/WAV bliver skrevet som `validation-output\piper-fallback.wav`
8. genstarter VoiceRig i `finally`, også hvis Piper-testen fejler
9. kræver at den genstartede service kører samme Git SHA og stadig er clean
10. kræver at ModelRig-backenden skifter tilbage til `provider == "voicerig"`

Fallback-testen nægter at bruge en ikke-loopback worker-URL. Hvis riggens interne
worker bruger en anden loopback-port, kan den angives med `-ModelRigWorkerUrl`.

Fallback-beviset skrives til:

```text
piper-fallback-report.json
```

Vigtige felter er:

```text
checkout_revision
stopped_voicerig_pid
fallback.provider
piper_synthesis.provider
piper_synthesis.output
piper_synthesis.bytes
piper_synthesis.riff
restarted_service_pid
restarted_service_revision
restored.provider
```

En gyldig fallback-PASS kræver hele kæden **voicerig → piper + rigtig WAV →
voicerig**. Dermed er et rent provider-skift ikke længere nok til at bestå.

## 8. Acceptance-record

Følgende værdier kopieres fra `validation-report.json` og
`piper-fallback-report.json` til PR #1:

- `source_evidence.checkout.revision`
- `source_evidence.checkout.branch`
- `source_evidence.checkout.dirty`
- `source_evidence.service.pid`
- `source_evidence.service.source.revision`
- `source_evidence.service.source.dirty`
- `source_evidence.same_revision`
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
- `piper_synthesis.provider`
- `piper_synthesis.output`
- `piper_synthesis.riff`
- `restarted_service_revision`
- `restored.provider`
- Piper fallback: PASS / FAIL

## Definition of Done

PR #1 må først gøres ready og merges, når:

1. GitHub CI er grøn på samme commit som `source_evidence.checkout.revision`.
2. Fysisk checkout er clean.
3. Aktiv VoiceRig-service er clean og kører samme revision (`same_revision=true`).
4. Setup model-warmup er PASS.
5. Preflight er PASS.
6. Fuld HTTP-baseret VoiceRig product-E2E er PASS.
7. Peak VRAM holder sig inden for RTX 3060 12 GB uden OOM.
8. Manuel lyttekontrol er PASS.
9. ModelRig backend rapporterer VoiceRig som aktiv TTS-provider med korrekt package.
10. Piper fallback producerer en rigtig WAV og VoiceRig restore er PASS.

Hvis ét punkt fejler, beholdes PR'en som draft og fejlen rettes på samme branch.
