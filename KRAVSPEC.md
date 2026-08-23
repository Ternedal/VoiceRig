# VoiceRig v1 — kravspecifikation og sporbarhed

## Produktmål

Den normale bruger skal kun:

1. trække 1–10 lyd- eller videofiler ind,
2. give stemmen et navn,
3. trykke **Opret stemme**.

VoiceRig skal derefter automatisk decode materialet, finde den rigtige person,
vælge gode references, oprette Chatterbox V3 conditioning, generere preview,
bygge en portabel `.mrvoice` og installere den til lokal ModelRig.

Hvis materialet indeholder flere omtrent lige tydelige personer, er den eneste
ekstra interaktion korte afspillelige speaker-prøver + **Brug denne stemme**.

## V1-krav — implementeret i software

- [x] MP3/WAV/M4A/FLAC/AAC/OGG/OPUS/WMA og MP4/MKV/MOV/AVI/WEBM/M4V accepteres via FFmpeg.
- [x] Input normaliseres til mono PCM16 WAV uden at ændre originalfilerne.
- [x] pyannote community-1 kører i separat CPU-only runtime.
- [x] VoiceRig sender canonical WAV som in-memory waveform til pyannote og er derfor ikke afhængig af TorchCodec file-decoding på Windows.
- [x] Samme person matches på tværs af filer med varighedsvægtede speaker-centroids.
- [x] Single-link speaker-chaining er regressionstestet væk.
- [x] Tydelig hovedperson vælges automatisk.
- [x] Tvetydigt materiale giver afspillelige stemmeprøver i UI i stedet for et gæt.
- [x] Brugerens speaker-valg genfindes via et taleturn-anker, ikke kun et rangnummer.
- [x] Manglende diarization fejler lukket i produktmode.
- [x] Flere korte rene turns kan stitches uden at kopiere lyd fra hullerne mellem dem.
- [x] Referencevalg kræver ca. 5,5–10 sekunders brugbar tale.
- [x] Primær reference + op til tre diverse backup-references produceres normalt.
- [x] Chatterbox Multilingual V3 er default engine; dansk (`da`) er default sprog.
- [x] Chatterbox V3 er pin'et til en verificeret Git source-revision frem for den ældre PyPI-0.1.7-kodeflade.
- [x] Hovedruntime bruger Torch/Torchaudio 2.6.0 CUDA; diarization bruger eksakt pyannote 4.0.7 + Torch/Torchaudio 2.8.0 + TorchCodec 0.7.0 CPU.
- [x] `.env` indlæses deterministisk; session/OS-env vinder.
- [x] pyannote telemetry er slået fra som standard.
- [x] Windows setup downloader og loader begge modelstacks som warmup.
- [x] UI låses indtil model-readiness-marker matcher den aktuelle runtime-kontrakt.
- [x] Chatterbox model caches og genbruges; kun ét voice-build kører ad gangen.
- [x] Conditioning + preview er atomisk under samme re-entrant GPU-lås.
- [x] Preview genbruger allerede prepared conditionals og beregner dem ikke to gange.
- [x] Voice-build og sidecar deler conditioning-identitet, så mutable modelstate ikke kan divergere fra cache-identiteten.
- [x] Preview og runtime-TTS gemmes som signed PCM16 WAV.
- [x] Reference, preview og fysisk testsyntese valideres på WAV, varighed og hørbar RMS.
- [x] `.mrvoice` indeholder manifest, checksums, primary reference, conditioning og preview.
- [x] `.mrvoice` kan indeholde backup-references.
- [x] Nye profiler registrerer Chatterbox source-revision.
- [x] Serialized conditioning genbruges kun ved matchende revision; ellers regenereres den fra `reference.wav`.
- [x] `.mrvoice` afviser path traversal, dubletter, krypterede/ukendte entries, checksum-fejl og ZIP-bomb-lignende størrelser.
- [x] Manifest afviser ugyldige typer, sprog, NaN/Infinity og out-of-range TTS-parametre.
- [x] Same-host profil installeres atomisk i `~/.kaliv/voices/` og markeres default.
- [x] VoiceRig har loopback TTS-sidecar til ModelRig.
- [x] ModelRig `main` har `.mrvoice`/VoiceRig-provider med Piper fallback.
- [x] Build og TTS rapporterer serverprocessens aktuelle/peak CUDA-memory til fysisk acceptance.
- [x] Fysisk validator bruger den rigtige VoiceRig HTTP-service, ikke en separat Chatterbox-model.
- [x] Fysisk ModelRig-validering bruger autentificeret backend `/api/v1/health/full`, ikke rå worker-port.
- [x] ModelRig PASS kan kræve `checks.tts.provider == "voicerig"` og korrekt aktiv package.
- [x] Setup genstarter en allerede kørende VoiceRig-service efter opdatering og verificerer aktiv Git HEAD.
- [x] Service health/readiness eksponerer PID og Git source revision til acceptance-evidence.
- [x] Originale inputfiler ændres aldrig.
- [x] Midlertidige arbejdsfiler ryddes op.
- [x] VoiceRig sender ikke kildeaudio til en cloudtjeneste.

## Fysisk acceptance — stadig åben

Software-CI kan ikke bevise følgende og PR #1 må derfor forblive draft:

- [ ] Windows setup/warmup PASS på den faktiske rig.
- [ ] Chatterbox V3 loader og genererer på RTX 3060 12 GB uden CUDA OOM.
- [ ] pyannote community-1 kører på rigtig inputaudio i CPU-runtime.
- [ ] Rigtige lyd-/videoklip producerer korrekt person/reference.
- [ ] Serverprocessens peak allocated/reserved VRAM holder sig inden for 12 GB-kortet.
- [ ] Dansk testsyntese er forståelig og stabil.
- [ ] Stemmeidentiteten er manuelt genkendelig som kilden.
- [ ] Speaker-embedding cosine registreres som kalibreringsdata (ingen hård tærskel endnu).
- [ ] ModelRig-backend rapporterer VoiceRig som aktiv TTS-provider med den netop byggede package.
- [ ] ModelRig kan faktisk afspille/syntetisere med stemmen i normal brugerflow.
- [ ] Piper fallback fungerer fortsat, når VoiceRig-sidecaren stoppes.

Den autoritative procedure ligger i `docs/RIG_ACCEPTANCE.md`.

## Definition of Done

VoiceRig v1 er først mergeklar, når **samme commit** har:

1. grøn GitHub CI,
2. clean fysisk checkout,
3. aktiv VoiceRig-service på samme Git HEAD,
4. setup/warmup PASS,
5. fuld VoiceRig HTTP E2E PASS,
6. peak VRAM PASS på RTX 3060 12 GB,
7. manuel lyd-/stemmelighed PASS,
8. ModelRig backend/provider/package PASS,
9. Piper fallback PASS.
