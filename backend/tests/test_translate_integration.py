"""Tests for the Amazon Translate / multilingual Polly integration.

Verifies that when an INFER payload carries targetLanguage='es':
  1. translate_service.translate_text is called with the English Bedrock output.
  2. polly_tts.synthesize is called with the Spanish voice ID 'Lupe'.
  3. The CAPTION event text reflects the translated string.

All AWS clients are monkeypatched; no real AWS calls are made.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


class _Ctx(SimpleNamespace):
    function_name = "NIMBUS_PROD_ProcessFrame"
    function_version = "$LATEST"
    memory_limit_in_mb = 1024
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:test"
    aws_request_id = "req-translate-test"


CTX = _Ctx()


def _event(target_language: str | None = None) -> dict:
    body: dict = {
        "action": "INFER",
        "sessionId": "aaaa0000-0000-4000-8000-000000000001",
        "roomId": "room-translate",
        "timestamp": "2026-04-19T10:00:00Z",
        "sequenceNumber": 1,
        "payload": {
            "token": "A",
            "includeFaceCrop": False,
        },
    }
    if target_language is not None:
        body["targetLanguage"] = target_language
    return {
        "requestContext": {
            "connectionId": "conn-translate",
            "domainName": "example.execute-api.us-east-1.amazonaws.com",
            "stage": "prod",
            "routeKey": "INFER",
        },
        "body": json.dumps(body),
    }


@pytest.fixture
def base_patches(monkeypatch):
    """Patch AWS-touching services used by every translate test."""
    from handlers import process_frame
    from services import sagemaker_inference, rekognition_emotion

    posts: list[dict] = []
    monkeypatch.setattr(
        process_frame, "post_to_connection",
        lambda event, conn, payload: posts.append({"conn": conn, "payload": payload}) or True,
    )
    monkeypatch.setattr(
        sagemaker_inference, "is_in_service", lambda: True,
    )
    # Return [EOS] token so the buffer flushes immediately on the first frame.
    monkeypatch.setattr(
        sagemaker_inference, "invoke",
        lambda kp: {"tokens": ["HELLO", "[EOS]"], "confidence": 0.9},
    )
    monkeypatch.setattr(
        rekognition_emotion, "detect_emotion",
        lambda b: ("CALM", 1.0, {"CALM": 1.0}),
    )
    monkeypatch.setattr(process_frame, "update_emotion", lambda sid, emo: None)
    monkeypatch.setattr(
        process_frame, "append_gloss",
        lambda *a, **kw: {"glossBuffer": ["X"] * 20},  # force flush via 20-token rule
    )
    monkeypatch.setattr(
        process_frame, "drain_buffer",
        lambda sid: ["HELLO", "[EOS]"],
    )
    monkeypatch.setattr(
        process_frame, "recent_captions",
        lambda sid, limit=3: [],
    )
    monkeypatch.setattr(process_frame, "store_caption", lambda sid, text: None)
    process_frame._last_token.clear()
    process_frame._session_emotion.clear()
    yield posts


def test_spanish_translate_called_and_lupe_voice_used(base_patches, monkeypatch):
    """targetLanguage='es' → translate_text called, Polly called with 'Lupe'."""
    from handlers import process_frame
    from services import translate_service
    from services.polly_tts import synthesize as real_synthesize

    translate_calls: list[dict] = []
    polly_calls: list[dict] = []

    monkeypatch.setattr(
        process_frame, "safe_interpret",
        lambda tokens, ctx, emotion="CALM": ("Hello world", False),
    )
    monkeypatch.setattr(
        translate_service, "translate_text",
        lambda text, lang: translate_calls.append({"text": text, "lang": lang}) or "Hola mundo",
    )
    monkeypatch.setattr(
        process_frame, "safe_synthesize",
        lambda ssml, voice_id, session_id: polly_calls.append({"voice": voice_id}) or "https://s3.example.com/audio.mp3",
    )
    monkeypatch.setattr(
        process_frame, "get_prosody_map",
        lambda: {"mappings": {"CALM": {"pitch": "medium", "rate": "medium", "volume": "medium"}}, "defaultVoiceId": "Matthew"},
    )

    resp = process_frame.handler(_event(target_language="es"), CTX)
    assert resp["statusCode"] == 200

    # translate must have been called
    assert translate_calls, "translate_text was not called for targetLanguage='es'"
    assert translate_calls[0]["lang"] == "es"
    assert translate_calls[0]["text"] == "Hello world"

    # Polly must have been called with the Spanish voice
    assert polly_calls, "safe_synthesize was not called"
    assert polly_calls[0]["voice"] == "Lupe", (
        f"Expected Polly voice 'Lupe' for Spanish, got '{polly_calls[0]['voice']}'"
    )

    # CAPTION payload should contain the translated text
    captions = [p["payload"] for p in base_patches if p["payload"].get("type") == "CAPTION"]
    assert captions, "No CAPTION event emitted"
    assert captions[0]["payload"]["text"] == "Hola mundo"


def test_english_skips_translate(base_patches, monkeypatch):
    """targetLanguage='en' → translate_text NOT called, default English voice used."""
    from handlers import process_frame
    from services import translate_service

    translate_calls: list[dict] = []

    monkeypatch.setattr(
        process_frame, "safe_interpret",
        lambda tokens, ctx, emotion="CALM": ("Hello world", False),
    )
    monkeypatch.setattr(
        translate_service, "translate_text",
        lambda text, lang: translate_calls.append({"text": text, "lang": lang}) or text,
    )
    polly_calls: list[dict] = []
    monkeypatch.setattr(
        process_frame, "safe_synthesize",
        lambda ssml, voice_id, session_id: polly_calls.append({"voice": voice_id}) or "https://s3.example.com/audio.mp3",
    )
    monkeypatch.setattr(
        process_frame, "get_prosody_map",
        lambda: {"mappings": {"CALM": {"pitch": "medium", "rate": "medium", "volume": "medium"}}, "defaultVoiceId": "Matthew"},
    )

    resp = process_frame.handler(_event(target_language="en"), CTX)
    assert resp["statusCode"] == 200

    assert not translate_calls, "translate_text must NOT be called for English"
    assert polly_calls and polly_calls[0]["voice"] == "Matthew"


def test_no_target_language_skips_translate(base_patches, monkeypatch):
    """Absent targetLanguage → translate_text NOT called."""
    from handlers import process_frame
    from services import translate_service

    translate_calls: list[dict] = []

    monkeypatch.setattr(
        process_frame, "safe_interpret",
        lambda tokens, ctx, emotion="CALM": ("Hello world", False),
    )
    monkeypatch.setattr(
        translate_service, "translate_text",
        lambda text, lang: translate_calls.append({"text": text, "lang": lang}) or text,
    )
    monkeypatch.setattr(
        process_frame, "safe_synthesize",
        lambda ssml, voice_id, session_id: "https://s3.example.com/audio.mp3",
    )
    monkeypatch.setattr(
        process_frame, "get_prosody_map",
        lambda: {"mappings": {"CALM": {"pitch": "medium", "rate": "medium", "volume": "medium"}}, "defaultVoiceId": "Matthew"},
    )

    resp = process_frame.handler(_event(target_language=None), CTX)
    assert resp["statusCode"] == 200
    assert not translate_calls, "translate_text must NOT be called when targetLanguage is absent"


def test_translate_failure_falls_back_to_english(base_patches, monkeypatch):
    """If translate_text raises, the English text is still delivered."""
    from handlers import process_frame
    from services import translate_service
    from common.errors import TranslateError

    polly_calls: list[dict] = []

    monkeypatch.setattr(
        process_frame, "safe_interpret",
        lambda tokens, ctx, emotion="CALM": ("Hello world", False),
    )
    monkeypatch.setattr(
        translate_service, "translate_text",
        lambda text, lang: (_ for _ in ()).throw(TranslateError("AWS quota exceeded")),
    )
    monkeypatch.setattr(
        process_frame, "safe_synthesize",
        lambda ssml, voice_id, session_id: polly_calls.append({"voice": voice_id}) or "https://s3.example.com/audio.mp3",
    )
    monkeypatch.setattr(
        process_frame, "get_prosody_map",
        lambda: {"mappings": {"CALM": {"pitch": "medium", "rate": "medium", "volume": "medium"}}, "defaultVoiceId": "Matthew"},
    )

    resp = process_frame.handler(_event(target_language="fr"), CTX)
    assert resp["statusCode"] == 200

    # Must still emit a CAPTION with English text (fallback)
    captions = [p["payload"] for p in base_patches if p["payload"].get("type") == "CAPTION"]
    assert captions, "CAPTION must be emitted even when translate fails"
    assert captions[0]["payload"]["text"] == "Hello world"

    # Must use English voice after translate failure
    assert polly_calls and polly_calls[0]["voice"] == "Matthew"


def test_voice_map_coverage():
    """All four required languages have a defined voice."""
    from services.translate_service import voice_for_language

    assert voice_for_language("en") == "Matthew"
    assert voice_for_language("es") == "Lupe"
    assert voice_for_language("fr") == "Lea"
    assert voice_for_language("ja") == "Takumi"
    # Unknown language falls back to English voice
    assert voice_for_language("xx") == "Matthew"
