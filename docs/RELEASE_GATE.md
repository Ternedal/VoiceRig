# VoiceRig V1 — final release gate

Denne gate køres **kun efter** den fulde fysiske rig-acceptance i
`docs/RIG_ACCEPTANCE.md`.

Målet er ét samlet, fail-closed releasebevis uden at uploade stemmeoptagelser,
`.mrvoice` eller WAV-filer til GitHub.

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
- ModelRig som ikke bruger VoiceRig/korrrekt package,
- Piper fallback uden rigtig RIFF/WAV,
- VoiceRig som ikke blev genetableret efter fallback-testen,
- manglende manuel kvalitetsgodkendelse.

Ved PASS oprettes:

```text
release-acceptance.json
```

Rapporten indeholder SHA-256 for de konkrete acceptance-artifacts, så den
manuelle lydvurdering kan bindes til præcis de filer, som maskinrapporterne
beskriver. Selve lydfilerne og `.mrvoice` forbliver lokale og er Git-ignorerede.

## 4. Merge-regel

PR #1 kan først gøres ready/merge, når:

1. `release-acceptance.json` siger `ok: true`,
2. `source.revision` er identisk med PR-head,
3. GitHub Actions er grøn på **samme PR-head**,
4. der ikke er nye review-blockers.

Hvis koden ændres efter den fysiske acceptance, er releasebeviset stale. Kør den
fysiske acceptance og release-gaten igen på den nye head.
