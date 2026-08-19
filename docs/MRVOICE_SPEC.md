# ModelRig Voice Package (`.mrvoice`) v1

`.mrvoice` er en ZIP-container med data-only indhold.

Obligatoriske filer:

```text
manifest.json
checksums.json
reference.wav
conditioning.pt
preview.wav
```

`manifest.json` indeholder formatversion, voice-id, navn, sprog, engine og defaultparametre. V1 bruger `chatterbox-multilingual` / `v3`.

`checksums.json` indeholder SHA-256 for alle binære payload-filer. Importører skal afvise mismatch og path traversal.

Referenceaudio gemmes altid, selv når `conditioning.pt` findes, så conditioning kan regenereres ved en fremtidig engine-opgradering.
