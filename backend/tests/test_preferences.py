"""Tests for handlers/preferences.py and voice preference lookup in process_frame."""
from __future__ import annotations

import json
import os

import pytest


# ── Preferences handler tests ────────────────────────────────────────────────


def _pref_event(body: dict | None = None, method: str = "POST") -> dict:
    return {
        "requestContext": {"http": {"method": method}},
        "body": json.dumps(body) if body is not None else None,
    }


@pytest.fixture
def patched_prefs(monkeypatch):
    """Patch DynamoDB table used by preferences handler."""
    from handlers import preferences

    stored: list[dict] = []

    class _FakeTable:
        def put_item(self, Item):
            stored.append(Item)

    monkeypatch.setattr(preferences, "_ddb_table", _FakeTable())
    monkeypatch.setattr(preferences, "_TABLE", "NIMBUS_TEST_UserPreferences")
    return stored


def test_save_valid_voice(patched_prefs):
    from handlers.preferences import handler
    resp = handler(_pref_event({"userId": "user-abc", "preferredVoiceId": "Joanna"}), None)
    assert resp["statusCode"] == 200
    data = json.loads(resp["body"])
    assert data["saved"] is True
    assert data["preferredVoiceId"] == "Joanna"
    assert patched_prefs == [{"userId": "user-abc", "preferredVoiceId": "Joanna"}]


def test_invalid_voice_rejected(patched_prefs):
    from handlers.preferences import handler
    resp = handler(_pref_event({"userId": "user-abc", "preferredVoiceId": "InvalidVoice"}), None)
    assert resp["statusCode"] == 400
    assert "preferredVoiceId" in json.loads(resp["body"])["error"]
    assert not patched_prefs


def test_missing_user_id_rejected(patched_prefs):
    from handlers.preferences import handler
    resp = handler(_pref_event({"preferredVoiceId": "Matthew"}), None)
    assert resp["statusCode"] == 400
    assert "userId" in json.loads(resp["body"])["error"]


def test_cors_preflight_returns_204():
    from handlers.preferences import handler
    resp = handler(_pref_event(method="OPTIONS"), None)
    assert resp["statusCode"] == 204
    assert resp["headers"].get("Access-Control-Allow-Origin") == "*"


def test_cors_headers_on_success(patched_prefs):
    from handlers.preferences import handler
    resp = handler(_pref_event({"userId": "u1", "preferredVoiceId": "Matthew"}), None)
    assert resp["headers"].get("Access-Control-Allow-Origin") == "*"


def test_invalid_json_returns_400(patched_prefs):
    from handlers.preferences import handler
    evt = {"requestContext": {"http": {"method": "POST"}}, "body": "not-json"}
    resp = handler(evt, None)
    assert resp["statusCode"] == 400


# ── Voice preference lookup in process_frame ─────────────────────────────────


class _Ctx:
    function_name = "NIMBUS_PROD_ProcessFrame"
    function_version = "$LATEST"
    memory_limit_in_mb = 1024
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:test"
    aws_request_id = "req-test"


def _infer_event(user_id: str | None = None) -> dict:
    body = {
        "action": "INFER",
        "sessionId": "22222222-2222-4222-8222-222222222222",
        "roomId": "room-2",
        "timestamp": "2026-04-19T10:00:00Z",
        "sequenceNumber": 1,
        "payload": {"token": "A", "includeFaceCrop": False},
    }
    if user_id:
        body["userId"] = user_id
    return {
        "requestContext": {
            "connectionId": "conn-xyz",
            "domainName": "example.execute-api.us-east-1.amazonaws.com",
            "stage": "dev",
            "routeKey": "INFER",
        },
        "body": json.dumps(body),
    }


@pytest.fixture
def pf_patched(monkeypatch):
    """Minimal patch set for process_frame to test voice selection."""
    from handlers import process_frame
    from services import sagemaker_inference, rekognition_emotion

    posts: list[dict] = []
    monkeypatch.setattr(process_frame, "post_to_connection",
                        lambda event, conn, payload: posts.append(payload) or True)
    monkeypatch.setattr(process_frame, "append_gloss",
                        lambda *a, **kw: {"glossBuffer": ["A"] * 20})  # force flush
    monkeypatch.setattr(process_frame, "drain_buffer",
                        lambda sid: ["STORE", "I", "GO"])
    monkeypatch.setattr(process_frame, "recent_captions", lambda sid, limit=3: [])
    monkeypatch.setattr(process_frame, "store_caption", lambda sid, text: None)
    monkeypatch.setattr(process_frame, "safe_interpret",
                        lambda tokens, ctx, emotion="CALM": ("I am going to the store.", False))
    monkeypatch.setattr(sagemaker_inference, "is_in_service", lambda: True)
    monkeypatch.setattr(sagemaker_inference, "invoke",
                        lambda kp: {"tokens": ["STORE"], "confidence": 0.9})
    monkeypatch.setattr(rekognition_emotion, "detect_emotion",
                        lambda b: ("CALM", 1.0, {"CALM": 1.0}))
    monkeypatch.setattr(process_frame, "update_emotion", lambda sid, emo: None)
    process_frame._last_token.clear()
    process_frame._session_emotion.clear()
    process_frame._prefs_table = None
    return posts


def test_default_voice_matthew_when_no_user(pf_patched, monkeypatch):
    """When no userId is in the payload, Polly should use the default voice (Matthew)."""
    from handlers import process_frame

    synthesize_calls: list[str] = []
    monkeypatch.setattr(process_frame, "safe_synthesize",
                        lambda ssml, voice, sid: synthesize_calls.append(voice) or "https://s3.example/audio.mp3")
    monkeypatch.setattr(process_frame, "get_prosody_map",
                        lambda: {"defaultVoiceId": "Matthew", "mappings": {"CALM": {"pitch": "+0%", "rate": "95%", "volume": "medium"}}})

    process_frame.handler(_infer_event(user_id=None), _Ctx())
    assert any(v == "Matthew" for v in synthesize_calls), "Default voice must be Matthew when no userId"


def test_custom_voice_joanna_from_dynamo(pf_patched, monkeypatch):
    """When DynamoDB returns preferredVoiceId=Joanna for the user, Polly must use Joanna."""
    from handlers import process_frame

    synthesize_calls: list[str] = []
    monkeypatch.setattr(process_frame, "safe_synthesize",
                        lambda ssml, voice, sid: synthesize_calls.append(voice) or "https://s3.example/audio.mp3")
    monkeypatch.setattr(process_frame, "get_prosody_map",
                        lambda: {"defaultVoiceId": "Matthew", "mappings": {"CALM": {"pitch": "+0%", "rate": "95%", "volume": "medium"}}})

    class _FakeTable:
        def get_item(self, Key):
            return {"Item": {"userId": Key["userId"], "preferredVoiceId": "Joanna"}}

    process_frame._prefs_table = _FakeTable()
    process_frame._USER_PREFS_TABLE = "NIMBUS_TEST_UserPreferences"

    process_frame.handler(_infer_event(user_id="user-joanna"), _Ctx())
    assert any(v == "Joanna" for v in synthesize_calls), "Must use Joanna when DynamoDB preference is set"


def test_fallback_to_default_when_dynamo_empty(pf_patched, monkeypatch):
    """When DynamoDB has no record for the user, fall back to the default voice."""
    from handlers import process_frame

    synthesize_calls: list[str] = []
    monkeypatch.setattr(process_frame, "safe_synthesize",
                        lambda ssml, voice, sid: synthesize_calls.append(voice) or "https://s3.example/audio.mp3")
    monkeypatch.setattr(process_frame, "get_prosody_map",
                        lambda: {"defaultVoiceId": "Matthew", "mappings": {"CALM": {"pitch": "+0%", "rate": "95%", "volume": "medium"}}})

    class _FakeTable:
        def get_item(self, Key):
            return {}  # no Item key → no preference stored

    process_frame._prefs_table = _FakeTable()
    process_frame._USER_PREFS_TABLE = "NIMBUS_TEST_UserPreferences"

    process_frame.handler(_infer_event(user_id="user-new"), _Ctx())
    assert any(v == "Matthew" for v in synthesize_calls), "Must fall back to Matthew when no DynamoDB entry"


def test_fallback_to_default_on_dynamo_error(pf_patched, monkeypatch):
    """DynamoDB errors in preference lookup must be swallowed; caption still delivered."""
    from handlers import process_frame

    synthesize_calls: list[str] = []
    monkeypatch.setattr(process_frame, "safe_synthesize",
                        lambda ssml, voice, sid: synthesize_calls.append(voice) or "https://s3.example/audio.mp3")
    monkeypatch.setattr(process_frame, "get_prosody_map",
                        lambda: {"defaultVoiceId": "Matthew", "mappings": {"CALM": {"pitch": "+0%", "rate": "95%", "volume": "medium"}}})

    class _BrokenTable:
        def get_item(self, Key):
            raise RuntimeError("DynamoDB unavailable")

    process_frame._prefs_table = _BrokenTable()
    process_frame._USER_PREFS_TABLE = "NIMBUS_TEST_UserPreferences"

    resp = process_frame.handler(_infer_event(user_id="user-broken"), _Ctx())
    assert resp["statusCode"] == 200
    assert any(v == "Matthew" for v in synthesize_calls), "Must fall back to Matthew on DynamoDB error"
