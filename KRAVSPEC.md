# VoiceRig v1 — condensed kravspecifikation

## Produktkrav

Den normale bruger skal kun:

1. Trække 1–10 lyd- eller videofiler ind.
2. Give stemmen et navn.
3. Trykke **Opret stemme**.

VoiceRig skal derefter automatisk decode mediet, finde tale, adskille talere når diarization er tilgængelig, vælge et godt referenceklip, oprette Chatterbox V3 conditioning, generere preview og levere en `.mrvoice`.

Hvis ModelRig kan kontaktes, installeres profilen automatisk. Hvis ikke, er `.mrvoice` stadig et fuldt, portabelt resultat.

## V1 acceptance

- MP3/WAV/M4A og MP4/MKV/MOV kan importeres via FFmpeg.
- Referencevalg kræver mindst cirka 5.5 sekunders brugbar tale.
- Dansk er default og Chatterbox Multilingual V3 er default engine.
- `.mrvoice` indeholder reference, conditioning, preview, manifest og SHA-256 checksums.
- Path traversal og checksum mismatch afvises.
- Originale inputfiler ændres aldrig.
- Midlertidige filer ryddes op.
- Ingen kildeaudio sendes til cloud af VoiceRig.
- ModelRig-integration går gennem backend-API'et, ikke direkte til worker-processen.
