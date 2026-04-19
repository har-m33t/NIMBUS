"""Amazon Translate service for multilingual ASL output.

Translates Bedrock English output into the caller's target language and
returns the appropriate Amazon Polly neural voice ID for that language.

Supported languages and voice mapping:
  en → Matthew (default, no translation call made)
  es → Lupe    (neural, US Spanish)
  fr → Lea     (neural, French)
  ja → Takumi  (neural, Japanese)

Fallback: any unmapped language code returns English voice.
"""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError

from common.errors import TranslateError

# Ordered from most common to least — add entries here to expand language support.
_VOICE_MAP: dict[str, str] = {
    "en": "Matthew",
    "es": "Lupe",
    "fr": "Lea",
    "ja": "Takumi",
}

_translate_client = None


def _client():
    global _translate_client
    if _translate_client is None:
        _translate_client = boto3.client("translate")
    return _translate_client


def translate_text(text: str, target_language: str) -> str:
    """Translate English text to target_language. Raises TranslateError on failure."""
    try:
        resp = _client().translate_text(
            Text=text,
            SourceLanguageCode="en",
            TargetLanguageCode=target_language,
        )
        return resp["TranslatedText"]
    except (ClientError, Exception) as exc:
        raise TranslateError(f"Translate failed [{target_language}]: {exc}") from exc


def voice_for_language(language_code: str) -> str:
    """Return the Polly neural voice ID for the given language code."""
    return _VOICE_MAP.get(language_code, _VOICE_MAP["en"])
