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

VoiceRig kan desuden gemme op til fem alternative rene references med **præcis**
disse navne:

```text
references/candidate_01.wav
references/candidate_02.wav
references/candidate_03.wav
references/candidate_04.wav
references/candidate_05.wav
```

Andre filer under `references/` er ikke gyldige v1-payloads. VoiceRig v1
producerer normalt højst tre backups. De vælges med en diversitets-gate, så
samme overlappende 10-sekunders vindue ikke fylder alle backup-slots.
Backup-references er en del af checksum-kontrakten og gør det muligt senere at
regenerere conditioning eller evaluere en ny engine uden de oprindelige video-
eller lydfiler.

## Manifest

Et nyt VoiceRig v1-manifest har formen:

```json
{
  "format": "modelrig-voice",
  "format_version": 1,
  "id": "anders-12345678",
  "name": "Anders",
  "language": "da",
  "engine": {
    "name": "chatterbox-multilingual",
    "model": "v3",
    "revision": "5de7a54aa4e5e2baadb0182dde554908b48b85c2"
  },
  "files": {
    "reference": "reference.wav",
    "conditioning": "conditioning.pt",
    "preview": "preview.wav"
  },
  "defaults": {
    "exaggeration": 0.5,
    "cfg_weight": 0.5,
    "temperature": 0.8
  }
}
```

`id` er en intern runtime-identitet og bliver bl.a. brugt som lokalt cache-
mappenavn. V1 kræver derfor et path-sikkert slug-format:

```text
^[a-z0-9æøå_-]{1,160}$
```

Det betyder: lowercase bogstaver, tal, `æøå`, `_` og `-`; ingen slash,
backslash, punktum, whitespace eller path-segmenter. Importer skal validere id'et
**før** runtime-materialisering.

`engine.revision` identificerer den eksakte Chatterbox-kilde, der producerede
den serialiserede `conditioning.pt`. Feltet er valgfrit på formatniveau for at
bevare læsning af tidlige v1-profiler, men nye VoiceRig-profiler skal skrive det.
Hvis feltet findes, skal det være et lowercase 40-tegns Git commit-id.

Importer skal validere typer og ranges før værdier sendes til en TTS-engine.
VoiceRigs v1-validator kræver finite tal og accepterer kun:

```text
exaggeration  0.0 .. 2.0
cfg_weight    0.0 .. 2.0
temperature   0.05 .. 5.0
```

JSON-konstanter som `NaN` og `Infinity` er ugyldige.

## Conditioning-portabilitet

`conditioning.pt` er en **optimering**, ikke den autoritative stemmekilde.
`reference.wav` er autoritativ.

Runtime-reglen er:

1. Hvis `engine.name/model` ikke er understøttet, afvis pakken.
2. Hvis `engine.revision` matcher den kørende VoiceRig-revision, må
   `conditioning.pt` indlæses direkte.
3. Hvis revisionen mangler, er anderledes eller den serialiserede conditioning
   ikke kan indlæses, skal runtime regenerere conditioning fra `reference.wav`.
4. Den regenererede conditioning kan caches lokalt, men ændrer ikke selve
   `.mrvoice`-pakken.

Dermed kan en profil overleve en fremtidig Chatterbox-opgradering uden at lade
binær modelstate foregive at være kompatibel på tværs af revisioner.

Runtime-cacheidentiteten skal desuden følge den konkrete package-fil (voice-id,
revision, path, mtime/size og device), så en erstattet pakke med samme voice-id
ikke kan genbruge stale mutable conditioning-state.

## Checksums

`checksums.json` indeholder lowercase SHA-256 for **præcis alle payload-filer**:
obligatoriske binære filer plus eventuelle dokumenterede `references/candidate_*.wav`.

`manifest.json` og `checksums.json` hasher ikke sig selv.

## Referenceaudio

`reference.wav` gemmes altid, selv når `conditioning.pt` findes. Preview og
VoiceRig-genereret runtime-TTS skrives som PCM signed 16-bit WAV for at holde
formatet entydigt på tværs af TorchAudio-backends.

Den primære reference skal være den reference, der blev brugt til at generere
`conditioning.pt`. Alternative references er regeneration/evalueringsmateriale.

## Atomisk oprettelse og erstatning

Et build med samme stemmeslug kan erstatte en eksisterende `.mrvoice`. V1-
implementationen må ikke skrive direkte oven i en kendt god profil.

VoiceRig skriver derfor først en sibling-tempfil, validerer **hele** den nye
pakke inklusive manifest/checksums og udfører derefter en atomisk `os.replace`.
Hvis skrivning eller validering fejler, skal den tidligere profil forblive
byte-for-byte urørt, og tempfilen skal ryddes op.

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
- path-lignende/ugyldige manifest-id'er
- ukendte payloadnavne
- andre `references/*` end `candidate_01.wav` … `candidate_05.wav`
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

`reference.wav` skal altid kunne bruges som regeneration-kilde. Backup-references
kan bruges til kvalitetsevaluering eller en fremtidig multi-reference-
regeneration, men er ikke nødvendige for at åbne en gyldig v1-pakke.
