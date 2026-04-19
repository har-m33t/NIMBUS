"""Phase 2 boundary detection tests for process_frame handler (letter/fingerspelling mode)."""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest


class _Ctx(SimpleNamespace):
    function_name = "NIMBUS_PROD_ProcessFrame"
    function_version = "$LATEST"
    memory_limit_in_mb = 1024
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:test"
    aws_request_id = "req-test"


CTX = _Ctx()
SESSION = "22222222-2222-4222-8222-222222222222"


def _event(seq: int = 1, token: str = "A") -> dict:
    body = {
        "action": "INFER",
        "sessionId": SESSION,
        "roomId": "room-2",
        "timestamp": "2026-04-18T12:00:00Z",
        "sequenceNumber": seq,
        "payload": {"token": token},
    }
    return {
        "requestContext": {
            "connectionId": "conn-xyz",
            "domainName": "x.execute-api.us-east-1.amazonaws.com",
            "stage": "dev",
            "routeKey": "INFER",
        },
        "body": json.dumps(body),
    }


@pytest.fixture
def patched_base(monkeypatch):
    """Minimal patches: post_to_connection + no-op store_caption. Clears dedup cache."""
    from handlers import process_frame

    posts: list[dict] = []
    monkeypatch.setattr(
        process_frame, "post_to_connection",
        lambda event, conn, payload: posts.append({"conn": conn, "payload": payload}) or True,
    )
    monkeypatch.setattr(process_frame, "store_caption", lambda sid, text: None)
    process_frame._last_token.clear()
    return posts


def test_caption_emitted_on_20_letter_boundary(monkeypatch, patched_base):
    from handlers import process_frame

    big_buf = list("ABCDEFGHIJKLMNOPQRST")  # 20 distinct single-char letters
    def fake_append(sid, tokens, cid, rid, emotion="CALM"):
        return {"glossBuffer": big_buf, "firstTokenAt": int(time.time() * 1000) - 100}

    monkeypatch.setattr(process_frame, "append_gloss", fake_append)
    monkeypatch.setattr(process_frame, "drain_buffer", lambda sid, sk="STATE": big_buf)
    monkeypatch.setattr(process_frame, "recent_captions", lambda sid, limit=3: [])
    monkeypatch.setattr(process_frame, "safe_interpret", lambda tokens, ctx, emotion: ("Some sentence.", False))
    monkeypatch.setattr(process_frame, "get_prosody_map", lambda: {
        "mappings": {"CALM": {"pitch": "0%", "rate": "medium", "volume": "medium"}},
        "defaultVoiceId": "Matthew",
    })
    monkeypatch.setattr(process_frame, "build_ssml", lambda t, **kw: f"<speak>{t}</speak>")
    monkeypatch.setattr(process_frame, "default_voice", lambda p: "Matthew")
    monkeypatch.setattr(process_frame, "safe_synthesize", lambda ssml, voice, sid: "https://s3.example.com/audio.mp3")

    process_frame.handler(_event(seq=1, token="A"), CTX)

    types = [p["payload"]["type"] for p in patched_base]
    assert "CAPTION" in types
    caption = next(p["payload"] for p in patched_base if p["payload"]["type"] == "CAPTION")
    assert caption["payload"]["text"] == "Some sentence."
    assert caption["payload"]["ssmlUrl"] == "https://s3.example.com/audio.mp3"


def test_caption_emitted_on_eos_token(monkeypatch, patched_base):
    from handlers import process_frame

    # drain_buffer returns multi-char tokens — not letter mode, passes straight to Bedrock
    gloss_buf = ["HELLO", "[EOS]"]

    def fake_append(sid, tokens, cid, rid, emotion="CALM"):
        return {"glossBuffer": gloss_buf, "firstTokenAt": int(time.time() * 1000) - 100}

    monkeypatch.setattr(process_frame, "append_gloss", fake_append)
    monkeypatch.setattr(process_frame, "drain_buffer", lambda sid, sk="STATE": gloss_buf)
    monkeypatch.setattr(process_frame, "recent_captions", lambda sid, limit=3: [])
    monkeypatch.setattr(process_frame, "safe_interpret", lambda tokens, ctx, emotion: ("Hello.", False))
    monkeypatch.setattr(process_frame, "get_prosody_map", lambda: {
        "mappings": {"CALM": {"pitch": "0%", "rate": "medium", "volume": "medium"}},
        "defaultVoiceId": "Matthew",
    })
    monkeypatch.setattr(process_frame, "build_ssml", lambda t, **kw: f"<speak>{t}</speak>")
    monkeypatch.setattr(process_frame, "default_voice", lambda p: "Matthew")
    monkeypatch.setattr(process_frame, "safe_synthesize", lambda ssml, voice, sid: None)

    # [EOS] is a multi-char token; _should_flush detects it in new_tokens
    process_frame.handler(_event(seq=2, token="[EOS]"), CTX)

    types = [p["payload"]["type"] for p in patched_base]
    assert "CAPTION" in types


def test_no_flush_below_limit(monkeypatch, patched_base):
    from handlers import process_frame

    def fake_append(sid, tokens, cid, rid, emotion="CALM"):
        return {"glossBuffer": list("ABC"), "firstTokenAt": int(time.time() * 1000) - 100}

    monkeypatch.setattr(process_frame, "append_gloss", fake_append)
    monkeypatch.setattr(process_frame, "drain_buffer", lambda sid, sk="STATE": None)

    process_frame.handler(_event(seq=3, token="A"), CTX)

    types = [p["payload"]["type"] for p in patched_base]
    assert "CAPTION" not in types


def test_new_caption_signal_emitted_with_caption(monkeypatch, patched_base):
    from handlers import process_frame

    big_buf = list("ABCDEFGHIJKLMNOPQRST")  # 20 distinct letters → triggers flush

    def fake_append(sid, tokens, cid, rid, emotion="CALM"):
        return {"glossBuffer": big_buf, "firstTokenAt": int(time.time() * 1000) - 100}

    monkeypatch.setattr(process_frame, "append_gloss", fake_append)
    monkeypatch.setattr(process_frame, "drain_buffer", lambda sid, sk="STATE": big_buf)
    monkeypatch.setattr(process_frame, "recent_captions", lambda sid, limit=3: [])
    monkeypatch.setattr(process_frame, "safe_interpret", lambda tokens, ctx, emotion: ("A sentence.", False))
    monkeypatch.setattr(process_frame, "get_prosody_map", lambda: {
        "mappings": {"CALM": {"pitch": "0%", "rate": "medium", "volume": "medium"}},
        "defaultVoiceId": "Matthew",
    })
    monkeypatch.setattr(process_frame, "build_ssml", lambda t, **kw: f"<speak>{t}</speak>")
    monkeypatch.setattr(process_frame, "default_voice", lambda p: "Matthew")
    monkeypatch.setattr(process_frame, "safe_synthesize", lambda ssml, voice, sid: None)

    process_frame.handler(_event(seq=1, token="B"), CTX)

    signals = [p["payload"] for p in patched_base if p["payload"]["type"] == "SIGNAL"]
    new_caption_signals = [s for s in signals if s.get("event") == "NEW_CAPTION"]
    assert new_caption_signals, "Expected NEW_CAPTION SIGNAL after flush"


def test_letters_reconstructed_to_words_before_bedrock(monkeypatch, patched_base):
    """Verify _letters_to_words is called: buffer ['H','E','L','L','O'] → Bedrock gets ['HELLO']."""
    from handlers import process_frame

    letter_buf = list("HELLO")  # 5 single-char letters
    received_tokens: list[list[str]] = []

    def fake_append(sid, tokens, cid, rid, emotion="CALM"):
        return {"glossBuffer": letter_buf, "firstTokenAt": int(time.time() * 1000) - 100}

    def capturing_interpret(tokens, ctx, emotion):
        received_tokens.append(list(tokens))
        return ("Hello.", False)

    monkeypatch.setattr(process_frame, "append_gloss", fake_append)
    monkeypatch.setattr(process_frame, "drain_buffer", lambda sid, sk="STATE": letter_buf)
    monkeypatch.setattr(process_frame, "recent_captions", lambda sid, limit=3: [])
    monkeypatch.setattr(process_frame, "safe_interpret", capturing_interpret)
    monkeypatch.setattr(process_frame, "get_prosody_map", lambda: {
        "mappings": {"CALM": {"pitch": "0%", "rate": "medium", "volume": "medium"}},
        "defaultVoiceId": "Matthew",
    })
    monkeypatch.setattr(process_frame, "build_ssml", lambda t, **kw: f"<speak>{t}</speak>")
    monkeypatch.setattr(process_frame, "default_voice", lambda p: "Matthew")
    monkeypatch.setattr(process_frame, "safe_synthesize", lambda ssml, voice, sid: None)

    # Force flush by returning 5-item buffer that exceeds... well, 5 < 20.
    # Use firstTokenAt in the past to trigger time-based flush.
    def fake_append_timed(sid, tokens, cid, rid, emotion="CALM"):
        return {
            "glossBuffer": letter_buf,
            "firstTokenAt": int(time.time() * 1000) - 11000,  # 11s ago → exceeds 10s limit
        }

    monkeypatch.setattr(process_frame, "append_gloss", fake_append_timed)

    process_frame.handler(_event(seq=1, token="H"), CTX)

    assert received_tokens, "safe_interpret was never called"
    # Letters should have been joined into one word token
    assert received_tokens[0] == ["HELLO"], f"Expected ['HELLO'], got {received_tokens[0]}"


def test_duplicate_letters_not_appended(monkeypatch, patched_base):
    """Holding the same letter for two frames should only append once."""
    from handlers import process_frame

    appended: list[list[str]] = []

    def fake_append(sid, tokens, cid, rid, emotion="CALM"):
        appended.append(list(tokens))
        return {"glossBuffer": tokens, "firstTokenAt": int(time.time() * 1000) - 100}

    monkeypatch.setattr(process_frame, "append_gloss", fake_append)
    monkeypatch.setattr(process_frame, "drain_buffer", lambda sid, sk="STATE": None)

    # Send the same letter twice
    process_frame.handler(_event(seq=1, token="A"), CTX)
    process_frame.handler(_event(seq=2, token="A"), CTX)

    # Only the first should have been appended
    assert len(appended) == 1, f"Expected 1 append, got {len(appended)}: {appended}"
    assert appended[0] == ["A"]
