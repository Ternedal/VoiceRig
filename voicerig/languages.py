from __future__ import annotations

from dataclasses import dataclass


# Chatterbox Multilingual V3 upstream language_id contract.
SUPPORTED_ENGINE_LANGUAGES = {
    "ar": "Arabic",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "ms": "Malay",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "sv": "Swedish",
    "sw": "Swahili",
    "tr": "Turkish",
    "zh": "Chinese",
}


@dataclass(frozen=True)
class LocaleChoice:
    code: str
    label: str

    @property
    def language_id(self) -> str:
        return self.code.split("-", 1)[0].lower()


LOCALES = (
    LocaleChoice("da-DK", "Dansk — Danmark"),
    LocaleChoice("en-US", "English — United States"),
    LocaleChoice("en-GB", "English — United Kingdom"),
    LocaleChoice("en-AU", "English — Australia"),
    LocaleChoice("en-CA", "English — Canada"),
    LocaleChoice("de-DE", "Deutsch — Deutschland"),
    LocaleChoice("de-AT", "Deutsch — Österreich"),
    LocaleChoice("de-CH", "Deutsch — Schweiz"),
    LocaleChoice("es-ES", "Español — España"),
    LocaleChoice("es-MX", "Español — México"),
    LocaleChoice("pt-PT", "Português — Portugal"),
    LocaleChoice("pt-BR", "Português — Brasil"),
    LocaleChoice("fr-FR", "Français — France"),
    LocaleChoice("fr-CA", "Français — Canada"),
    LocaleChoice("ar-SA", "العربية — السعودية"),
    LocaleChoice("el-GR", "Ελληνικά — Ελλάδα"),
    LocaleChoice("fi-FI", "Suomi — Suomi"),
    LocaleChoice("he-IL", "עברית — ישראל"),
    LocaleChoice("hi-IN", "हिन्दी — भारत"),
    LocaleChoice("it-IT", "Italiano — Italia"),
    LocaleChoice("ja-JP", "日本語 — 日本"),
    LocaleChoice("ko-KR", "한국어 — 대한민국"),
    LocaleChoice("ms-MY", "Bahasa Melayu — Malaysia"),
    LocaleChoice("nl-NL", "Nederlands — Nederland"),
    LocaleChoice("no-NO", "Norsk — Norge"),
    LocaleChoice("pl-PL", "Polski — Polska"),
    LocaleChoice("ru-RU", "Русский — Россия"),
    LocaleChoice("sv-SE", "Svenska — Sverige"),
    LocaleChoice("sw-TZ", "Kiswahili — Tanzania"),
    LocaleChoice("tr-TR", "Türkçe — Türkiye"),
    LocaleChoice("zh-CN", "中文 — 中国大陆"),
    LocaleChoice("zh-TW", "中文 — 台灣"),
)

_LOCALE_BY_CODE = {item.code.lower(): item for item in LOCALES}
_DEFAULT_LOCALE = {
    "ar": "ar-SA",
    "da": "da-DK",
    "de": "de-DE",
    "el": "el-GR",
    "en": "en-US",
    "es": "es-ES",
    "fi": "fi-FI",
    "fr": "fr-FR",
    "he": "he-IL",
    "hi": "hi-IN",
    "it": "it-IT",
    "ja": "ja-JP",
    "ko": "ko-KR",
    "ms": "ms-MY",
    "nl": "nl-NL",
    "no": "no-NO",
    "pl": "pl-PL",
    "pt": "pt-PT",
    "ru": "ru-RU",
    "sv": "sv-SE",
    "sw": "sw-TZ",
    "tr": "tr-TR",
    "zh": "zh-CN",
}

US_ACCENTS = (
    ("general-american", "General American"),
    ("southern-us", "Southern US"),
    ("texas-south-central", "Texas / South Central"),
    ("new-york-city", "New York City"),
    ("new-england-boston", "New England / Boston"),
    ("midwest-great-lakes", "Midwest / Great Lakes"),
    ("west-coast-california", "West Coast / California"),
)
_ACCENTS_BY_LOCALE = {
    "en-us": dict(US_ACCENTS),
}

_PREVIEW_TEXTS = {
    "ar": "مرحبًا. هذا مثال على الصوت الجديد في VoiceRig.",
    "da": "Hej. Dette er en prøve på den nye stemme i VoiceRig.",
    "de": "Hallo. Dies ist eine Probe der neuen Stimme in VoiceRig.",
    "el": "Γεια σας. Αυτό είναι ένα δείγμα της νέας φωνής στο VoiceRig.",
    "en": "Hello. This is a sample of the new voice in VoiceRig. I parked the car near the water and I'll call you tomorrow.",
    "es": "Hola. Esta es una muestra de la nueva voz en VoiceRig.",
    "fi": "Hei. Tämä on näyte VoiceRigin uudesta äänestä.",
    "fr": "Bonjour. Voici un échantillon de la nouvelle voix dans VoiceRig.",
    "he": "שלום. זוהי דוגמה לקול החדש ב-VoiceRig.",
    "hi": "नमस्ते। यह VoiceRig में नई आवाज़ का एक नमूना है।",
    "it": "Ciao. Questo è un esempio della nuova voce in VoiceRig.",
    "ja": "こんにちは。これはVoiceRigの新しい音声のサンプルです。",
    "ko": "안녕하세요. 이것은 VoiceRig의 새 음성 샘플입니다.",
    "ms": "Hai. Ini ialah contoh suara baharu dalam VoiceRig.",
    "nl": "Hallo. Dit is een voorbeeld van de nieuwe stem in VoiceRig.",
    "no": "Hei. Dette er en prøve av den nye stemmen i VoiceRig.",
    "pl": "Cześć. To jest próbka nowego głosu w VoiceRig.",
    "pt": "Olá. Esta é uma amostra da nova voz no VoiceRig.",
    "ru": "Здравствуйте. Это образец нового голоса в VoiceRig.",
    "sv": "Hej. Det här är ett prov på den nya rösten i VoiceRig.",
    "sw": "Habari. Huu ni mfano wa sauti mpya katika VoiceRig.",
    "tr": "Merhaba. Bu, VoiceRig'deki yeni sesin bir örneğidir.",
    "zh": "你好。这是 VoiceRig 中新声音的示例。",
}


def base_language(value: str) -> str:
    return str(value or "").strip().replace("_", "-").split("-", 1)[0].lower()


def engine_language_id(value: str) -> str:
    language = base_language(value)
    if language not in SUPPORTED_ENGINE_LANGUAGES:
        raise ValueError(f"Sproget {value!r} understøttes ikke af den aktive multilingual-motor.")
    return language


def normalize_build_locale(value: str) -> str:
    raw = str(value or "").strip().replace("_", "-")
    language = base_language(raw)
    if language not in SUPPORTED_ENGINE_LANGUAGES:
        raise ValueError(f"Sproget {value!r} understøttes ikke af VoiceRig.")
    if raw.lower() == language:
        # Keep legacy/base-language callers stable. The UI uses full locale tags.
        return language
    choice = _LOCALE_BY_CODE.get(raw.lower())
    if choice is None:
        raise ValueError(f"Locale {value!r} er ikke en understøttet VoiceRig-variant.")
    return choice.code


def default_locale(language: str) -> str:
    return _DEFAULT_LOCALE[engine_language_id(language)]


def accent_choices(locale: str) -> tuple[tuple[str, str], ...]:
    mapping = _ACCENTS_BY_LOCALE.get(str(locale or "").strip().lower(), {})
    return tuple(mapping.items())


def validate_accent(locale: str, accent: str | None) -> str | None:
    raw = str(accent or "").strip().lower()
    if not raw:
        return None
    choices = _ACCENTS_BY_LOCALE.get(str(locale or "").strip().lower(), {})
    if raw not in choices:
        raise ValueError(f"Accentprofilen {accent!r} understøttes ikke for {locale}.")
    return raw


def preview_text(locale: str) -> str:
    language = engine_language_id(locale)
    return _PREVIEW_TEXTS[language]


def public_voice_options() -> dict:
    return {
        "locales": [
            {
                "code": item.code,
                "label": item.label,
                "language_id": item.language_id,
                "accents": [
                    {"code": code, "label": label}
                    for code, label in accent_choices(item.code)
                ],
            }
            for item in LOCALES
        ],
        "default_locale": "da-DK",
        "accent_semantics": "reference-led-metadata",
    }
