"""Phase 2 boundary detection tests for process_frame handler."""
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


def _event(seq: int = 1, tokens: list[str] | None = None) -> dict:
    body = {
        "action": "INFER",
        "sessionId": SESSION,
        "roomId": "room-2",
        "timestamp": "2026-04-18T12:00:00Z",
        "sequenceNumber": seq,
        "payload": {"keypoints": {"leftHand": [], "rightHand": [], "pose": []}, "includeFaceCrop": False},
    }
    return {"requestContext": {"connectionId": "conn-xyz", "domainName": "x.execute-api.us-east-1.amazonaws.com", "stage": "dev", "routeKey": "INFER"}, "body": json.dumps(body)}


@pytest.fixture
def patched_base(monkeypatch):
    """Minimal patches: sagemaker + post_to_connection + cold-start + no-op store_caption."""
    from handlers import process_frame
    from services import sagemaker_inference

    posts: list[dict] = []
    monkeypatch.setattr(process_frame, "post_to_connection",
                        lambda event, conn, payload: posts.append({"conn": conn, "payload": payload}) or True)
    monkeypatch.setattr(process_frame, "store_caption", lambda sid, text: None)
    monkeypatch.setattr(sagemaker_inference, "is_in_service", lambda: True)
    process_frame._cold_start_checked.clear()
    return posts


def test_caption_emitted_on_15_token_boundary(monkeypatch, patched_base):
    from handlers import process_frame

    # Fake append_gloss returning a 15-token buffer
    big_buf = ["TOK"] * 15
    def fake_append(sid, tokens, cid, rid, emotion="CALM"):
        return {"glossBuffer": big_buf, "firstTokenAt": int(time.time() * 1000) - 100, "timestamp": "2026-04-18T12:00:00.000Z"}
    monkeypatch.setattr(process_frame, "append_gloss", fake_append)
    monkeypatch.setattr(process_frame, "drain_buffer", lambda sid, sk="STATE": big_buf)
    monkeypatch.setattr(process_frame, "recent_captions", lambda sid, limit=3: [])
    monkeypatch.setattr(process_frame, "safe_interpret", lambda tokens, ctx, emotion: ("I go store.", False))
    monkeypatch.setattr(process_frame, "get_prosody_map", lambda: {"mappings": {"CALM": {"pitch": "0%", "rate": "medium", "volume": "medium"}}, "defaultVoiceId": "Matthew"})
    monkeypatch.setattr(process_frame, "build_ssml", lambda t, **kw: f"<speak>{t}</speak>")
    monkeypatch.setattr(process_frame, "default_voice", lambda p: "Matthew")
    monkeypatch.setattr(process_frame, "safe_synthesize", lambda ssml, voice, sid: "https://s3.example.com/audio.mp3")
    from services import sagemaker_inference
    monkeypatch.setattr(sagemaker_inference, "invoke", lambda kp: {"tokens": ["TOK"], "confidence": 0.9})

    process_frame.handler(_event(seq=1), CTX)

    types = [p["payload"]["type"] for p in patched_base]
    assert "CAPTION" in types
    caption = next(p["payload"] for p in patched_base if p["payload"]["type"] == "CAPTION")
    assert caption["payload"]["text"] == "I go store."
    assert caption["payload"].get("audioUrl") is None
    
    signals = [p["payload"] for p in patched_base if p["payload"]["type"] == "SIGNAL"]
    audio_signals = [s for s in signals if s.get("event") == "AUDIO_READY"]
    assert len(audio_signals) == 1
    assert audio_signals[0]["payload"]["audioUrl"] == "https://s3.example.com/audio.mp3"

def test_caption_emitted_on_eos_token(monkeypatch, patched_base):
    from handlers import process_frame

    def fake_append(sid, tokens, cid, rid, emotion="CALM"):
        return {"glossBuffer": tokens, "firstTokenAt": int(time.time() * 1000) - 100, "timestamp": "2026-04-18T12:00:00.000Z"}
    monkeypatch.setattr(process_frame, "append_gloss", fake_append)
    monkeypatch.setattr(process_frame, "drain_buffer", lambda sid, sk="STATE": ["HELLO", "[EOS]"])
    monkeypatch.setattr(process_frame, "recent_captions", lambda sid, limit=3: [])
    monkeypatch.setattr(process_frame, "safe_interpret", lambda tokens, ctx, emotion: ("Hello.", False))
    monkeypatch.setattr(process_frame, "get_prosody_map", lambda: {"mappings": {"CALM": {"pitch": "0%", "rate": "medium", "volume": "medium"}}, "defaultVoiceId": "Matthew"})
    monkeypatch.setattr(process_frame, "build_ssml", lambda t, **kw: f"<speak>{t}</speak>")
    monkeypatch.setattr(process_frame, "default_voice", lambda p: "Matthew")
    monkeypatch.setattr(process_frame, "safe_synthesize", lambda ssml, voice, sid: None)
    from services import sagemaker_inference
    monkeypatch.setattr(sagemaker_inference, "invoke", lambda kp: {"tokens": ["HELLO", "[EOS]"], "confidence": 0.95})

    process_frame.handler(_event(seq=2), CTX)

    types = [p["payload"]["type"] for p in patched_base]
    assert "CAPTION" in types


def test_no_flush_below_limit(monkeypatch, patched_base):
    from handlers import process_frame

    def fake_append(sid, tokens, cid, rid, emotion="CALM"):
        return {"glossBuffer": ["TOK"] * 3, "firstTokenAt": int(time.time() * 1000) - 100, "timestamp": "2026-04-18T12:00:00.000Z"}
    monkeypatch.setattr(process_frame, "append_gloss", fake_append)
    monkeypatch.setattr(process_frame, "drain_buffer", lambda sid, sk="STATE": None)
    from services import sagemaker_inference
    monkeypatch.setattr(sagemaker_inference, "invoke", lambda kp: {"tokens": ["TOK"], "confidence": 0.9})

    process_frame.handler(_event(seq=3), CTX)

    types = [p["payload"]["type"] for p in patched_base]
    assert "CAPTION" not in types


def test_new_caption_signal_emitted_with_caption(monkeypatch, patched_base):
    from handlers import process_frame

    big_buf = ["A"] * 15
    def fake_append(sid, tokens, cid, rid, emotion="CALM"):
        return {"glossBuffer": big_buf, "firstTokenAt": int(time.time() * 1000) - 100, "timestamp": "2026-04-18T12:00:00.000Z"}
    monkeypatch.setattr(process_frame, "append_gloss", fake_append)
    monkeypatch.setattr(process_frame, "drain_buffer", lambda sid, sk="STATE": big_buf)
    monkeypatch.setattr(process_frame, "recent_captions", lambda sid, limit=3: [])
    monkeypatch.setattr(process_frame, "safe_interpret", lambda tokens, ctx, emotion: ("A.", False))
    monkeypatch.setattr(process_frame, "get_prosody_map", lambda: {"mappings": {"CALM": {"pitch": "0%", "rate": "medium", "volume": "medium"}}, "defaultVoiceId": "Matthew"})
    monkeypatch.setattr(process_frame, "build_ssml", lambda t, **kw: f"<speak>{t}</speak>")
    monkeypatch.setattr(process_frame, "default_voice", lambda p: "Matthew")
    monkeypatch.setattr(process_frame, "safe_synthesize", lambda ssml, voice, sid: None)
    from services import sagemaker_inference
    monkeypatch.setattr(sagemaker_inference, "invoke", lambda kp: {"tokens": ["A"], "confidence": 0.9})

    process_frame.handler(_event(seq=1), CTX)

    signals = [p["payload"] for p in patched_base if p["payload"]["type"] == "SIGNAL"]
    new_caption_signals = [s for s in signals if s.get("event") == "NEW_CAPTION"]
    assert new_caption_signals, "Expected NEW_CAPTION SIGNAL after flush"
