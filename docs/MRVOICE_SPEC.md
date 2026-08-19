# ModelRig Voice Package (`.mrvoice`) v1

`.mrvoice` er en versionsstyret ZIP-container med **data-only** indhold. Den må
ikke indeholde scripts, executables, DLL'er eller plugins.

## Obligatoriske filer

```text
manifest.json
checksums.json
reference.wav
conditioning.pt
preview.wav
```

## Valgfrie backup-references

VoiceRig kan desuden gemme op til fem alternative rene references:

```text
references/candidate_01.wav
references/candidate_02.wav
...
references/candidate_05.wav
```

VoiceRig v1 producerer normalt højst tre backups. De vælges med en diversitets-
gate, så samme overlappende 10-sekunders vindue ikke fylder alle backup-slots.
Backup-references er en del af checksum-kontrakten og gør det muligt senere at
regenerere conditioning eller evaluere en ny engine uden de oprindelige video-
eller lydfiler.

## Manifest

`manifest.json` indeholder:

- `format = "modelrig-voice"`
- `format_version = 1`
- voice-id og navn
- sprogkode
- engine + model
- de tre obligatoriske filreferencer
- TTS-defaults

V1 produceres med `chatterbox-multilingual` / `v3`.

Importer skal validere typer og ranges før værdier sendes til en TTS-engine.
VoiceRigs v1-validator kræver finite tal og accepterer kun:

```text
exaggeration  0.0 .. 2.0
cfg_weight    0.0 .. 2.0
temperature   0.05 .. 5.0
```

JSON-konstanter som `NaN` og `Infinity` er ugyldige.

## Checksums

`checksums.json` indeholder lowercase SHA-256 for **præcis alle payload-filer**:
obligatoriske binære filer plus eventuelle `references/*`.

`manifest.json` og `checksums.json` hasher ikke sig selv.

## Referenceaudio

`reference.wav` gemmes altid, selv når `conditioning.pt` findes. Preview og
VoiceRig-genereret runtime-TTS skrives som PCM signed 16-bit WAV for at holde
formatet entydigt på tværs af TorchAudio-backends.

Den primære reference skal være den reference, der blev brugt til at generere
`conditioning.pt`. Alternative references er regeneration/evalueringsmateriale.

## Sikkerhedsgrænser

VoiceRig v1 validerer ZIP-metadata **før** payloads læses i hukommelsen:

```text
Maks. entries                  10
Maks. samlet uncompressed      128 MiB
manifest.json/checksums.json   256 KiB pr. fil
reference/preview/backup WAV    16 MiB pr. fil
conditioning.pt                 64 MiB
```

Importer skal desuden afvise:

- absolutte paths
- `..` path traversal
- backslash-baserede archive paths
- ukendte payloadnavne
- dublerede archive entries
- krypterede entries
- manglende obligatoriske filer
- manglende/ekstra checksums
- checksum-mismatch
- ukendt format/version
- ugyldigt manifest-schema eller TTS-ranges

## Kompatibilitet

En v1-importer må ikke antage, at fremtidige `.mrvoice`-versioner har samme
struktur. `format_version` skal kontrolleres før payloaden fortolkes.

Hvis et fremtidigt Chatterbox-conditioning-format ikke længere kan indlæses,
skal `reference.wav` være den autoritative regeneration-kilde. Backup-references
kan bruges til kvalitetsevaluering eller en fremtidig regeneration-strategi,
men er ikke nødvendige for at åbne en gyldig v1-pakke.
