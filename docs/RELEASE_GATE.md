# VoiceRig V1 — final release gate

Denne gate køres **kun efter** den fulde fysiske rig-acceptance i
`docs/RIG_ACCEPTANCE.md`.

Målet er ét samlet, fail-closed releasebevis uden at uploade stemmeoptagelser,
`.mrvoice` eller WAV-filer til GitHub.

Den konkrete immutable release-ref, commit og grønne CI-runs dokumenteres i den
aktuelle autoritative acceptance-issue og PR #1. Der hardcodes derfor ikke live
SHA eller run-numre i denne fil. Hvis den pinned VoiceRig-commit ændres, er
tidligere fysisk acceptance stale og skal køres igen.

## 0. Dansk motorbeslutning, når flere kandidater evalueres

Når en release vælger mellem flere danske motorer, registreres lyttebeslutningen
separat fra den efterfølgende produktions-acceptance:

```powershell
.\record-engine-decision.ps1 `
  -Winner rost `
  -ChatterboxScore 2 `
  -RostScore 5 `
  -OmniVoiceScore 4 `
  -DecisionNote "Røst var klart mest naturlig på dansk og sagde hele teksten" `
  -ChatterboxNote "Svensk klang" `
  -RostNote "Naturlig dansk og genkendelig stemme" `
  -OmniVoiceNote "God accent, men enkelte gentagelser" `
  -TestText "Hej, jeg taler dansk. Rødgrød med fløde.","København, høre, gøre og selvfølgelig."
```

Dette opretter `engine-decision.json`. Rapporten binder beslutningen til:

- et clean checkout og dets Git SHA/root,
- de eksakte Chatterbox-, Røst- og OmniVoice source/model-revisioner,
- en samlet 1–5-score for alle tre kandidater,
- en eksplicit winner eller `none`,
- korte manuelle noter,
- SHA-256 + længde for de faktiske testtekster.

Rapporten gemmer **ikke** rå testtekster, profilidentitet, source audio eller
genereret lyd. `engine-decision.json` er Git-ignoreret som standard. En navngiven
winner skal have en entydigt højere score end de andre; ved uafgjort bruges
`-Winner none`, så evidence ikke kan påstå en klar vinder, som tallene ikke viser.

Dette beslutningsbevis erstatter ikke den endelige fysiske release-acceptance.
Når den valgte motor er integreret som produktionsmotor, skal hele acceptance-
forløbet nedenfor køres igen på den nye immutable release-SHA.

## 1. Kør hele den automatiske fysiske test

På RTX 3060-riggen, fra det clean checkout af den pinned release-ref:

```powershell
.\validate-rig.ps1 `
  -Source "C:\testdata\voice-01.mp4","C:\testdata\voice-02.m4a" `
  -Name "VoiceRig Acceptance" `
  -RequireModelRig `
  -RequirePiperFallback
```

Dette skal give PASS og oprette mindst:

```text
validation-report.json
piper-fallback-report.json
validation-output\*.mrvoice
validation-output\*-reference.wav
validation-output\*-validation.wav
validation-output\piper-fallback.wav
```

Maskinbeviset binder ikke kun til Git SHA. VoiceRig-serviceidentiteten fryses ved
processtart, og validation kræver samme clean **startup revision + checkout-root**
som acceptance-processen. En stale proces eller en anden clone på samme SHA kan
derfor ikke bestå.

## 2. Lyt

Afspil både den udtrukne reference og VoiceRig-syntesen.

Godkend kun kvaliteten hvis:

- referencefilen indeholder den ønskede person og ikke en anden speaker,
- dansk tale er tydelig og forståelig,
- stemmeidentiteten er genkendelig,
- der ikke er alvorlige metalliske artefakter, gentagelsesloops eller hallucineret tale.

Speaker-cosine i `validation-report.json` er fortsat kun en informationsmåling;
den må ikke erstatte lyttekontrollen før en tærskel er kalibreret på rigtige samples.

## 3. Lav det samlede release-verdict

Efter lytning:

```powershell
.\complete-acceptance.ps1 `
  -QualityPass `
  -QualityNote "Tydelig dansk, genkendelig stemme, ingen alvorlige artefakter"
```

`-QualityPass` skal være eksplicit. En tom kvalitetsnote accepteres ikke.

Scriptet læser de to maskinrapporter igen og afviser blandt andet:

- dirty eller ændret Git HEAD,
- acceptance kørt på en anden revision eller checkout-root,
- VoiceRig-service fra en anden root, revision eller dirty startup-tilstand,
- manglende eller flyttede artifacts,
- manglende diarization,
- TTS som ikke brugte CUDA eller den forventede `.mrvoice`,
- manglende peak-VRAM-data,
- ModelRig som ikke bruger VoiceRig/korrekt package,
- Piper fallback uden rigtig RIFF/WAV,
- fallback/restore som ikke bruger samme `.mrvoice`, root og revision som den fysiske E2E,
- VoiceRig som ikke blev genetableret efter fallback-testen,
- manglende manuel kvalitetsgodkendelse.

Slutgaten genvaliderer `.mrvoice` samt reference-, VoiceRig- og Piper-WAV igen
efter lyttekontrollen. Dermed kan ændrede eller beskadigede lokale artifacts ikke
bestå på et tidligere maskin-PASS.

Ved PASS oprettes `release-acceptance.json`. Rapporten indeholder SHA-256 for de
konkrete acceptance-artifacts. Selve lydfilerne og `.mrvoice` forbliver lokale og
Git-ignorerede.

## 4. Software/distribution gate

Alle autoritative GitHub Actions-workflows på **samme pinned VoiceRig commit**
skal være grønne. Gaten omfatter:

1. pytest + `compileall`,
2. browser-JavaScript syntax,
3. PowerShell parsing, inklusive Windows PowerShell 5.1,
4. wheel + sdist build,
5. installation af wheel i separat venv og `pip check`,
6. installeret Linux-service HTTP smoke,
7. installeret Windows-service HTTP smoke,
8. installerens faktiske retry/stopfunktion mod en editable Windows-service,
9. filfrigivelse af `voicerig.exe` før runtime-mutation,
10. separat Windows lifecycle A/B-checkout smoke, som beviser:
   - stale service afvises efter HEAD-skift,
   - en anden checkout på samme SHA ikke accepteres som den lokale service,
   - foreign uninstall ikke stopper den ejende checkout,
   - ejende checkout kan stoppe service/launcher og fjerne sin egen runtime.

Et grønt unit- eller editable-checkout alene er derfor ikke nok til release.

## 5. Merge-regel

PR #1 kan først gøres ready/merge, når:

1. `release-acceptance.json` siger `ok: true`,
2. final `source.revision` og `source.root` matcher den pinned release-kandidat,
3. validation evidence har `same_revision == true` og `same_root == true`,
4. Piper fallback/restore matcher samme root + revision,
5. alle autoritative Actions-workflows er grønne på **samme commit**,
6. der ikke er nye review-blockers.

Hvis koden ændres efter den fysiske acceptance, er releasebeviset stale. Kør den
fysiske acceptance og release-gaten igen på den nye pinned kandidat.
