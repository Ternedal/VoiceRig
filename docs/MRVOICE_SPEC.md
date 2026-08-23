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

Et aktuelt dansk VoiceRig v1-manifest kan fx have formen:

```json
{
  "format": "modelrig-voice",
  "format_version": 1,
  "id": "anders-12345678",
  "name": "Anders",
  "language": "da-DK",
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

Tidlige v1-profiler med base-language som `"da"` og den oprindelige
Chatterbox V3-engine er fortsat gyldige. Locale- og engine-udvidelser må ikke
gøre eksisterende v1-profiler ulæselige.

`id` er en intern runtime-identitet og bliver bl.a. brugt som lokalt cache-
mappenavn. V1 kræver derfor et path-sikkert slug-format:

```text
^[a-z0-9æøå_-]{1,160}$
```

Det betyder: lowercase bogstaver, tal, `æøå`, `_` og `-`; ingen slash,
backslash, punktum, whitespace eller path-segmenter. Importer skal validere id'et
**før** runtime-materialisering.

### Sprog og locale

`language` kan være enten et historisk base-language-id (`da`, `en`, `de`) eller
en VoiceRig-locale (`da-DK`, `en-US`, `en-GB`, `de-DE`, osv.).

Locale må **ikke** videresendes blindt som engine language-id. Runtime skal mappe
den til motorens dokumenterede base-language:

```text
da-DK -> da
en-US -> en
en-GB -> en
de-DE -> de
pt-BR -> pt
```

Dermed kan profilen bevare region/locale uden at sende ugyldige værdier som
`language_id="en-US"` til Chatterbox.

### Valgfri accentmetadata

V1 tillader det additive, valgfrie top-level-felt `accent`:

```json
{
  "language": "en-US",
  "accent": "southern-us"
}
```

Fravær af `accent` er den historiske v1-kontrakt og skal fortsat accepteres.
VoiceRig validerer accent mod den valgte locale. I den nuværende V1-kontrakt er
amerikanske regionale accentprofiler registreret på `en-US`; de må ikke sættes
på fx `en-GB`, `de-DE` eller `da-DK`.

Accentmetadata er i V1 **reference-led**. Det er ikke et skjult Chatterbox
language-id eller en separat model. En `en-US`-profil med `accent="new-york-city"`
kører stadig med engine `language_id="en"`; referenceaudio skal bære den faktiske
regionale accent. Metadataen bruges til UX/QA og gør senere dedikeret
accent-engine-routing mulig uden nyt package-format.

Se også `docs/LANGUAGE_LOCALE_ACCENT.md`.

`engine.revision` identificerer den eksakte model-/kilde-revision, der producerede
den serialiserede `conditioning.pt`. Feltet er valgfrit på formatniveau for at
bevare læsning af tidlige v1-profiler, men nye VoiceRig-profiler skal skrive det.
Hvis feltet findes, skal det være et lowercase 40-tegns commit-id.

### Engine-specifikke options

Gamle Chatterbox V3-profiler har ingen `engine.options` og forbliver gyldige
uændret. En kendt, pinnet engine kan have ekstra generation-controls, som ikke
hører til de tre fælles `defaults`. De gemmes i så fald eksplicit under
`engine.options`, så en profils lydadfærd ikke afhænger af skjulte runtime-defaults.

Røst v3 bruger eksempelvis:

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

Fysisk RC22-RC24-evidence har gjort Røst til den foretrukne danske
produktionsvej. Det ændrer ikke formatreglen om, at engine/model/revision skal
være eksplicit og pinnet i den konkrete profil.

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
5. Engine generation skal bruge det base-language-id, der er mappet fra
   manifestets `language`/locale; locale må ikke videresendes som et ukendt
   engine-id.

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

Ved reference-led accentprofiler skal referenceaudio desuden være den primære
bærer af den ønskede regionale accent; metadata alene ændrer ikke stemmens
udtale.

## Atomisk oprettelse og erstatning

Et build med samme stemmeslug kan erstatte en eksisterende `.mrvoice`. V1-
implementationen må ikke skrive direkte oven i en kendt god profil.

VoiceRig skriver derfor først en sibling-tempfil, validerer **hele** den nye
pakke inklusive manifest/checksums og udfører derefter en atomisk `os.replace`.
Hvis skrivning eller validering fejler, skal den tidligere profil forblive
byte-for-byte urørt, og tempfilen skal ryddes op.

Engine-migration skal bevare voice-id, navn, language/locale, eventuel accent og
stored references, medmindre en eksplicit fremtidig migration beskriver andet.

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
- ukendt locale/base-language
- accent, der ikke er registreret for den valgte locale

## Kompatibilitet

En v1-importer må ikke antage, at fremtidige `.mrvoice`-versioner har samme
struktur. `format_version` skal kontrolleres før payloaden fortolkes.

`engine.options` og `accent` er bagudkompatible, valgfrie manifest-udvidelser
inden for v1. Fravær betyder den oprindelige v1-kontrakt. Importer må aldrig
opfinde ukendte engine-options, locales eller accentkoder eller sende dem videre
uden validering.

`reference.wav` skal altid kunne bruges som regeneration-kilde for en engine,
der eksplicit understøtter den referenceform. Backup-references kan bruges til
kvalitetsevaluering eller en fremtidig multi-reference-regeneration, men er ikke
nødvendige for at åbne en gyldig v1-pakke.
