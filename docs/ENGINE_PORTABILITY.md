# VoiceRig engine-portabilitet

Dette dokument beskriver den motor-uafhængige kontrakt, der ligger **efter** den
frosne RC19 A/B-kandidat. RC19 ændres ikke af arbejdet her.

## Formål

En `.mrvoice` skal repræsentere en stemme, ikke være en engangscontainer for én
bestemt TTS-model. Den autoritative stemmekilde er derfor `reference.wav` samt de
dokumenterede backup-references. `conditioning.pt` og `preview.wav` er
engine-specifikke afledte artefakter.

Det giver tre vigtige egenskaber:

1. en modelrevision kan skiftes uden de oprindelige video-/lydfiler,
2. en kendt ny engine kan få ny conditioning ud fra samme stemmereference,
3. migration kan ske atomisk uden at ødelægge en kendt god profil ved fejl.

## Engine-katalog

`voicerig/engines/catalog.py` er den lette, torch-frie kontrakt for kendte
engines. Den indeholder:

- aktiv produktionsengine (`CURRENT_ENGINE`),
- kendte evaluerings-/migrationsmål,
- eksakt engine/model/revision-identitet,
- fælles TTS-defaults,
- engine-specifikke generation-options og ranges,
- kompatibilitetsklassifikation.

En kendt engine i kataloget er **ikke** det samme som en aktiv produktionsengine.
Røst v3 står i kataloget for at gøre A/B og en eventuel migration reproducerbar;
den bliver først produktionsengine efter fysisk kvalitetsverdict.

## Kompatibilitetsstater

VoiceRig klassificerer validerede profiler som:

- `direct`: engine/model/revision matcher aktiv runtime.
- `runtime-rebuild`: samme aktive engine/model, men conditioning skal regenereres
  fra `reference.wav` pga. en anden/manglende revision.
- `reference-portable`: kendt engine, men ikke aktiv produktionsruntime. Profilens
  autoritative reference kan bruges ved en eksplicit migration.
- `unsupported`: ukendt engine/model. VoiceRig må ikke gætte på kompatibilitet.

Biblioteks-API'et returnerer denne klassifikation additivt som `compatibility`.
Det ændrer ikke profilen og starter ikke en migration.

## Engine-options i `.mrvoice` v1

De oprindelige v1-profiler har kun de fælles defaults:

- `exaggeration`
- `cfg_weight`
- `temperature`

Det forbliver gyldigt uændret.

Hvis en kendt engine kræver yderligere generation-controls, kan de gemmes under
`engine.options`. Når feltet findes, er kontrakten fail-closed:

- engine-revisionen skal være eksakt pinned og kendt,
- options-sættet skal være komplet,
- ukendte felter afvises,
- bool/non-finite/out-of-range værdier afvises.

For den nuværende Røst v3-kandidat er de ekstra options:

```json
{
  "repetition_penalty": 2.0,
  "min_p": 0.05,
  "top_p": 0.95
}
```

Dermed bliver et eventuelt fremtidigt Røst-package reproducerbart og er ikke
afhængigt af skjulte Python-defaults.

## Atomisk engine-migration

`voicerig/profiles/migration.py` opdeler migration i to trin.

### 1. Plan

`migration_plan(package, target_engine)` validerer kilden og beskriver:

- source/target engine,
- voice-id,
- sprog,
- antal backup-references,
- at ny conditioning og preview er nødvendige.

Planen muterer intet.

### 2. Rebuild

`rebuild_package_for_engine(...)` forventer, at target-engine allerede har
genereret ny `conditioning.pt` og `preview.wav`. Helperen:

1. validerer den eksisterende `.mrvoice`,
2. udtrækker kun dokumenteret `reference.wav` og backup-references til privat
   temp-storage,
3. bevarer voice-id, navn og sprog,
4. bygger et nyt target-engine manifest med eksplicitte options,
5. skriver til sibling-temp,
6. validerer hele den nye pakke,
7. erstatter først derefter output atomisk.

`output` må være samme path som source. Hvis rebuild fejler før valid erstatning,
forbliver den kendte gode source byte-for-byte urørt.

## ModelRig

Pinned ModelRig RC12 fortolker ikke `.mrvoice`-manifestets enginefelter. Den ser
installerede `.mrvoice`-filer, spørger VoiceRig-sidecaren om status og sender TTS
til sidecaren. Derfor kan det additive `engine.options`-felt implementeres i
VoiceRig uden en samtidig ModelRig-formatændring.

ModelRig E2E skal stadig genkøres efter et reelt produktionsengine-skift, fordi
provider/fallback-adfærd skal fysisk bevises på den endelige VoiceRig-SHA.

## Beslutning efter RC19 A/B

### Hvis Røst er klart bedre

Næste releasearbejde skal:

1. gøre den pinnede Røst-spec til aktiv dansk engine,
2. warmup/readiness skal bruge samme katalog-spec,
3. profile-build skal generere Røst-conditioning/preview,
4. runtime skal dispatch'e Røst packages med manifestets validerede options,
5. eksisterende danske profiler skal tilbydes eksplicit atomisk migration fra
   deres `reference.wav` i stedet for automatisk skjult omskrivning,
6. fuld fysisk VoiceRig + ModelRig + Piper acceptance skal køres på den nye SHA.

### Hvis Røst ikke er klart bedre

Røst må ikke aktiveres som default. Katalog-/migrationslaget kan stadig genbruges
til næste dansk engine-kandidat, mens RC19-resultatet dokumenteres som et fysisk
modelverdict.

## Release-isolation

Den frosne fysiske kandidat er fortsat:

- ref: `release/voicerig-v1-physical-rc19`
- SHA: `2cf2dfb7eefdd6d08d000a13cab0d693f790861f`

Alt portabilitetsarbejde efter denne SHA ligger kun på `agent/voicerig-mvp` og
må ikke bruges som erstatning for RC19-evidence. En senere release-candidate skal
have sin egen pin og exact-head CI efter motorbeslutningen.
