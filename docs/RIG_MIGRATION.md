# VoiceRig old-rig -> new-rig migration

VoiceRig code, Python dependencies and model readiness are rebuilt by the normal
Windows installer. User state is moved separately with
`migrate-state-windows.ps1` so machine-local caches and secrets are not mistaken
for portable data.

## Portable state

A migration archive contains:

- every valid `.mrvoice` profile found in the VoiceRig library;
- valid `.mrvoice` profiles that exist only in ModelRig's local voice directory;
- ModelRig's selected/default `.mrvoice` package name;
- bounded VoiceRig job metadata;
- the original private input files required by `queued`, `running`,
  `needs_speaker` and `needs_reference` jobs so VoiceRig can recover them after
  the move.

The profile set is a union of VoiceRig and ModelRig. If the same filename exists
in both locations with different bytes, export stops instead of guessing which
voice is authoritative.

A resumable job is also fail-closed: if its job metadata says an input is needed
but that file is missing, export stops rather than producing an archive that
would look successful but cannot recover the job.

## Deliberately excluded

The archive never contains:

- `.env`, `HF_TOKEN`, `MODELRIG_TOKEN` or other credentials;
- `model-readiness.json`;
- logs or support bundles;
- `runtimes/` engine environments;
- `tts-runtime/` materialized package cache;
- convenience `*-reference.wav` copies next to `.mrvoice` files;
- downloaded model caches or Python virtual environments.

Those are either secrets, diagnostic material or machine-derived state. The new
rig must regenerate them through `install-windows.ps1`/the ModelRig bootstrap.

## Export on the old rig

Run from a clean current VoiceRig checkout:

```powershell
powershell -ExecutionPolicy Bypass -File .\migrate-state-windows.ps1 `
  -Action Export `
  -OutDir D:\VoiceRigMigration
```

The operator verifies that any service on port 8765 belongs to this checkout,
stops the owned VoiceRig process/launcher, creates and verifies the archive, and
then restarts the old service if it was running.

Two files are produced:

```text
voicerig-migration-YYYYMMDD-HHMMSS.tar.gz
voicerig-migration-YYYYMMDD-HHMMSS.tar.gz.migration.json
```

The sidecar binds the archive SHA-256 to the source Git revision and records only
non-secret migration metadata. Copy **both** files to the new rig.

If the archive reports `contains_private_job_inputs=true`, it includes source
audio/video from resumable jobs. Treat the archive as sensitive personal data
while storing or transporting it.

## Verify without stopping VoiceRig

```powershell
powershell -ExecutionPolicy Bypass -File .\migrate-state-windows.ps1 `
  -Action Verify `
  -Archive D:\VoiceRigMigration\voicerig-migration-YYYYMMDD-HHMMSS.tar.gz
```

Verify checks the sidecar SHA-256, migration inventory, every archived file hash,
all `.mrvoice` package checksums and resumable-job input completeness.

## Import on the new rig

First install VoiceRig normally on the new rig. Then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\migrate-state-windows.ps1 `
  -Action Import `
  -Archive D:\VoiceRigMigration\voicerig-migration-YYYYMMDD-HHMMSS.tar.gz
```

Import verifies the full archive before stopping the service. It refuses to
clobber existing voices/jobs/default state by default. After the service is
stopped, a failed or partial restore is **not** automatically restarted.
Successful import starts VoiceRig through the normal verified
`start-windows.ps1 -NoBrowser` path and reports `/api/readiness` afterwards.

For a deliberately disposable new-rig state, explicit overwrite is available:

```powershell
powershell -ExecutionPolicy Bypass -File .\migrate-state-windows.ps1 `
  -Action Import `
  -Archive D:\VoiceRigMigration\voicerig-migration-YYYYMMDD-HHMMSS.tar.gz `
  -ForceRestore
```

Do not use `-ForceRestore` on a VoiceRig installation whose current voices or
jobs you care about.

## What still needs manual configuration

Secrets are not portable by design. Reconfigure any required `HF_TOKEN` and
ModelRig authentication on the new machine. Model/model-readiness state should
come from the new machine's normal installation and warmup, not the old rig.

Keep the old rig intact until the new VoiceRig service starts, its profiles are
visible, the intended default voice is active in ModelRig, and a real TTS request
has been heard successfully.
