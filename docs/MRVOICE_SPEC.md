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

Et aktuelt dansk VoiceRig v1-manifest har formen:

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
    "cfg_weight": 0.0,
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

`engine.revision` identificerer den eksakte model-/kilde-revision, der producerede
den serialiserede `conditioning.pt`. Feltet er valgfrit på formatniveau for at
bevare læsning af tidlige v1-profiler, men nye VoiceRig-profiler skal skrive det.
Hvis feltet findes, skal det være et lowercase 40-tegns commit-id.

### Engine-specifikke options

Gamle og nuværende Chatterbox V3-profiler har ingen `engine.options` og forbliver
gyldige uændret. En kendt, pinnet engine kan dog have ekstra generation-controls,
som ikke hører til de tre fælles `defaults`. De gemmes i så fald eksplicit under
`engine.options`, så en profils lydadfærd ikke afhænger af skjulte runtime-defaults.

Eksempel på den kendte Røst v3-kandidat:

```json
{
  "engine": {
    "name": "chatterbox-multilingual",
    "model": "roest-v3-chatterbox-500m",
    "revision": "cd451fdc474aabd229fa0c6b6818f4b34382917e",
    "options": {
      "repetition_penalty": 2.0,
      "min_p": 0.05,
      "top_p": 0.95
    }
  },
  "defaults": {
    "exaggeration": 0.5,
    "cfg_weight": 0.5,
    "temperature": 0.8
  }
}
```

At Røst er kendt i format-/kataloglaget betyder **ikke**, at den er valgt som
produktionsmotor. En sådan beslutning kræver separat fysisk kvalitetsacceptance.

Når `engine.options` findes, gælder fail-closed-regler:

- engine name/model/revision skal matche en eksakt kendt pinned engine,
- options skal være et JSON-objekt,
- options-sættet skal være komplet for den engine,
- ukendte option-navne afvises,
- bool, `NaN`, `Infinity` og værdier uden for engine-specifikke ranges afvises.

Importer skal desuden validere de fælles TTS-defaults før værdier sendes til en
TTS-engine. VoiceRigs v1-validator kræver finite tal og accepterer kun:

```text
exaggeration  0.0 .. 2.0
cfg_weight    0.0 .. 2.0
temperature   0.05 .. 5.0
```

JSON-konstanter som `NaN` og `Infinity` er ugyldige.

## Conditioning-portabilitet

`conditioning.pt` er en **optimering**, ikke den autoritative stemmekilde.
`reference.wav` er autoritativ.

VoiceRig beskriver en valideret profils kompatibilitet uden automatisk at ændre
pakken:

- `direct`: engine/model/revision matcher den aktive produktionsruntime.
- `runtime-rebuild`: engine/model kan køres direkte, men serialized conditioning
  tilhører en anden/manglende revision og regenereres derfor fra `reference.wav`.
- `reference-portable`: engine er kendt, men ikke aktiv produktionsruntime;
  stemmen kan migreres ved at genbruge `reference.wav`, når den engine aktiveres.
- `unsupported`: engine/model er ukendt; VoiceRig må ikke gætte på en migration.

Runtime-reglen for den aktive engine er:

1. Hvis `engine.name/model` ikke er aktivt understøttet, afvis syntese i stedet
   for at migrere stiltiende.
2. Hvis `engine.revision` matcher den kørende VoiceRig-revision, må
   `conditioning.pt` indlæses direkte.
3. Hvis revisionen mangler, er anderledes eller den serialiserede conditioning
   ikke kan indlæses, skal runtime regenerere conditioning fra `reference.wav`.
4. Den regenererede conditioning kan caches lokalt, men ændrer ikke selve
   `.mrvoice`-pakken.

Dermed kan en profil overleve en modelopgradering — og for kendte engine-skift
kan den autoritative reference bevares — uden at binær modelstate foregiver at
være kompatibel på tværs af modeller/revisioner.

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
- ugyldige/ukendte engine-options

## Kompatibilitet

En v1-importer må ikke antage, at fremtidige `.mrvoice`-versioner har samme
struktur. `format_version` skal kontrolleres før payloaden fortolkes.

`engine.options` er en bagudkompatibel, valgfri manifest-udvidelse inden for v1;
fravær betyder den oprindelige v1-kontrakt. Importer må aldrig opfinde ukendte
engine-options eller sende dem videre uden validering.

`reference.wav` skal altid kunne bruges som regeneration-kilde for en engine,
der eksplicit understøtter den referenceform. Backup-references kan bruges til
kvalitetsevaluering eller en fremtidig multi-reference-regeneration, men er ikke
nødvendige for at åbne en gyldig v1-pakke.
