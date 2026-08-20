# VoiceRig V1 — final release gate

Denne gate køres **kun efter** den fulde fysiske rig-acceptance i
`docs/RIG_ACCEPTANCE.md`.

Målet er ét samlet, fail-closed releasebevis uden at uploade stemmeoptagelser,
`.mrvoice` eller WAV-filer til GitHub.

Den aktuelle releasekandidat er altid **PR-head på tidspunktet for den fysiske
acceptance**. Der hardcodes derfor ikke en commit-SHA i denne fil: hvis head
ændres, er tidligere fysisk acceptance stale og skal køres igen.

## 1. Kør hele den automatiske fysiske test

På RTX 3060-riggen, fra et clean checkout af den PR-head der skal releases:

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

## 2. Lyt

Afspil både den udtrukne reference og VoiceRig-syntesen.

Godkend kun kvaliteten hvis:

- referencefilen indeholder den ønskede person og ikke en anden speaker,
- dansk tale er tydelig og forståelig,
- stemmeidentiteten er genkendelig,
- der ikke er alvorlige metalliske artefakter, gentagelsesloops eller
  hallucineret tale.

Speaker-cosine i `validation-report.json` er fortsat kun en informationsmåling;
den må ikke erstatte lyttekontrollen før en tærskel er kalibreret på rigtige
samples.

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
- acceptance kørt på en anden revision,
- VoiceRig-service fra en anden/dirty revision,
- manglende eller flyttede artifacts,
- manglende diarization,
- TTS som ikke brugte CUDA eller den forventede `.mrvoice`,
- manglende peak-VRAM-data,
- ModelRig som ikke bruger VoiceRig/korrekt package,
- Piper fallback uden rigtig RIFF/WAV,
- fallback/restore som ikke bruger samme `.mrvoice` som den fysiske E2E,
- VoiceRig som ikke blev genetableret efter fallback-testen,
- manglende manuel kvalitetsgodkendelse.

Slutgaten genvaliderer `.mrvoice` samt reference-, VoiceRig- og Piper-WAV igen
efter lyttekontrollen. Dermed kan ændrede eller beskadigede lokale artifacts ikke
bestå på et tidligere maskin-PASS.

Ved PASS oprettes:

```text
release-acceptance.json
```

Rapporten indeholder SHA-256 for de konkrete acceptance-artifacts, så den
manuelle lydvurdering kan bindes til præcis de filer, som maskinrapporterne
beskriver. Selve lydfilerne og `.mrvoice` forbliver lokale og er Git-ignorerede.

## 4. Software/distribution gate

GitHub Actions på **samme PR-head** skal være grøn. Den autoritative CI-gate
omfatter ikke kun editable tests, men også den pakke der faktisk kan distribueres:

1. pytest + `compileall`,
2. PowerShell-syntax,
3. build af wheel og sdist,
4. installation af wheel i separat venv uden for source-træet,
5. `pip check`,
6. versionskontrakt mellem package metadata, `voicerig.__version__`, FastAPI og health,
7. verificering af at UI-asset og `voicerig`-entrypoint findes i wheel'en.

Et grønt editable checkout er derfor ikke nok til release.

## 5. Merge-regel

PR #1 kan først gøres ready/merge, når:

1. `release-acceptance.json` siger `ok: true`,
2. `source.revision` er identisk med PR-head,
3. GitHub Actions er grøn på **samme PR-head**, inklusive wheel/sdist-gaten,
4. der ikke er nye review-blockers.

Hvis koden ændres efter den fysiske acceptance, er releasebeviset stale. Kør den
fysiske acceptance og release-gaten igen på den nye head.
