# VoiceRig language, locale and accent contract

VoiceRig separates three concepts that must not be conflated:

1. **Engine language id** — the code the TTS engine officially accepts, e.g. `en`, `da`, `de`.
2. **Locale** — the user-facing language/region stored in the voice profile, e.g. `en-US`, `en-GB`, `de-DE`, `da-DK`.
3. **Accent profile** — optional regional metadata, currently used for reference-led QA and future engine routing, e.g. `southern-us` or `new-york-city`.

## Runtime mapping

A locale is never forwarded blindly to Chatterbox. VoiceRig maps it to the documented base language id:

```text
da-DK -> da
en-US -> en
en-GB -> en
de-DE -> de
pt-BR -> pt
```

This prevents an apparently useful locale picker from producing unsupported calls such as `language_id="en-US"`.

## Danish default

Physical RC22-RC24 listening established Røst v3 as the preferred Danish production engine. New Danish profiles therefore use Røst for both reference auditions and final conditioning/package generation.

Other supported languages continue to use the pinned Chatterbox Multilingual V3 runtime unless a language-specific engine is separately evaluated and accepted.

## US English regional accents

V1 exposes the following optional US accent profiles:

- `general-american` — General American
- `southern-us` — Southern US
- `texas-south-central` — Texas / South Central
- `new-york-city` — New York City
- `new-england-boston` — New England / Boston
- `midwest-great-lakes` — Midwest / Great Lakes
- `west-coast-california` — West Coast / California

These are **not separate Chatterbox models or language ids**. Chatterbox still receives `language_id="en"`.

The actual regional accent must therefore be represented in the reference material. VoiceRig stores the accent profile so:

- auditions and human QA can be evaluated against the intended accent,
- the library can display the intended regional profile,
- future dedicated accent engines can be routed without changing the voice identity or inventing a new package format.

Selecting `Southern US` does not transform a General American reference into a Southern accent by itself.

## `.mrvoice` metadata

Locale is stored in the existing `language` field:

```json
{
  "language": "en-US"
}
```

An optional accent is additive v1 metadata:

```json
{
  "language": "en-US",
  "accent": "southern-us"
}
```

Profiles without `accent` remain valid. Engine migration must preserve both locale and accent metadata.

## Fail-closed rules

VoiceRig rejects:

- unknown engine base languages,
- unknown locales,
- accent codes not registered for the selected locale,
- US regional accents attached to `en-GB`, German, Danish, or other unrelated locales.

The UI obtains the same catalog from `/api/voice-options`; it does not maintain a separate hardcoded runtime list.
