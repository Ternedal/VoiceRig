# ModelRig integration contract

VoiceRig expects ModelRig to expose:

```http
POST /api/v1/voices/import
Content-Type: multipart/form-data
voice=<file.mrvoice>
```

Expected success body:

```json
{"ok": true, "voice_id": "...", "name": "..."}
```

ModelRig should validate the `.mrvoice` manifest and checksums, install it in its voice registry, and map `engine.name=chatterbox-multilingual` to a Chatterbox provider. Existing Piper voices remain supported separately.
