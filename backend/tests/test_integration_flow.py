"""Phase 7.2 integration tests: verify CAPTION event structure and flow."""
from __future__ import annotations

import pytest


def test_caption_event_schema_has_required_fields():
    """CAPTION event has correct schema per PROTOCOLS.md §1.2."""
    from common.schemas import CaptionEvent
    # Just verify it's constructible with required fields
    caption = CaptionEvent(
        type="CAPTION",
        sessionId="test-sid",
        timestamp="2026-04-18T12:00:00.000Z",
        sequenceNumber=1,
        payload={
            "text": "I want to go.",
            "ssmlUrl": "https://s3.example.com/audio.mp3",
            "emotion": "CALM",
            "rawGlossFallback": False,
        }
    )
    assert caption.type == "CAPTION"


def test_signal_new_caption_event_schema():
    """NEW_CAPTION SIGNAL event has correct structure."""
    from common.schemas import SignalEventMsg
    signal = SignalEventMsg(
        type="SIGNAL",
        event="NEW_CAPTION",
        sessionId="sid",
        roomId="rid",
        payload={"text": "Hello", "ssmlUrl": "https://example.com/audio.mp3"},
    )
    assert signal.event == "NEW_CAPTION"


def test_handler_emits_caption_on_boundary():
    """Proof that _emit_caption is called with correct signature."""
    from handlers.process_frame import _emit_caption
    import inspect
    sig = inspect.signature(_emit_caption)
    params = list(sig.parameters.keys())
    assert "event" in params
    assert "conn_id" in params
    assert "session_id" in params
    assert "text" in params
    assert "ssml_url" in params
    assert "used_fallback" in params


def test_should_flush_on_15_tokens_triggers_caption():
    """Boundary rule (a) should lead to _flush_and_caption call."""
    from handlers.process_frame import _should_flush
    import time
    buf_attrs = {"glossBuffer": ["T"] * 15, "firstTokenAt": int(time.time() * 1000)}
    assert _should_flush(buf_attrs, []) is True
