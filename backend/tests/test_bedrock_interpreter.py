"""Phase 3 tests for Bedrock interpreter. All AWS calls monkeypatched."""
from __future__ import annotations

import pytest
from common.errors import BedrockError, RateLimitExceeded


@pytest.fixture(autouse=True)
def _patch_rate_limit(monkeypatch):
    import services.bedrock_interpreter as bi
    monkeypatch.setattr(bi, "acquire_or_raise", lambda **kw: None)


def _make_bedrock_response(text: str):
    import json
    from io import BytesIO
    body = json.dumps({"content": [{"text": text}]})
    return {"body": BytesIO(body.encode())}


def test_interpret_returns_english(monkeypatch):
    import services.bedrock_interpreter as bi
    monkeypatch.setattr(bi, "_bedrock", lambda: type("C", (), {
        "invoke_model": lambda *a, **kw: _make_bedrock_response("I want to go to the store.")
    })())
    text, fallback = bi.safe_interpret(["I", "WANT", "GO", "STORE"])
    assert text == "I want to go to the store."
    assert fallback is False


def test_safe_interpret_falls_back_on_error(monkeypatch):
    import services.bedrock_interpreter as bi
    def _fail(*a, **kw):
        raise Exception("timeout")
    monkeypatch.setattr(bi, "_bedrock", lambda: type("C", (), {"invoke_model": _fail})())
    text, fallback = bi.safe_interpret(["HELLO", "WORLD"])
    assert text == "HELLO WORLD"
    assert fallback is True


def test_rate_limit_exceeded_returns_raw_gloss(monkeypatch):
    import services.bedrock_interpreter as bi
    monkeypatch.setattr(bi, "acquire_or_raise", lambda **kw: (_ for _ in ()).throw(RateLimitExceeded("busy")))
    text, fallback = bi.safe_interpret(["SIGN", "HERE"])
    assert text == "SIGN HERE"
    assert fallback is True


def test_recent_captions_included_in_prompt():
    import services.bedrock_interpreter as bi
    prompt = bi._build_prompt(["GO"], ["Hello world"], "CALM")
    assert "Hello world" in prompt
    assert "GO" in prompt
    assert "CALM" in prompt
