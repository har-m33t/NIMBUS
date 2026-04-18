"""Phase 5 tests for Polly TTS service. All AWS calls monkeypatched."""
from __future__ import annotations

from io import BytesIO
import pytest
from common.errors import PollyError


def _fake_polly(audio=b"MP3DATA"):
    return type("P", (), {
        "synthesize_speech": lambda *a, **kw: {"AudioStream": BytesIO(audio)}
    })()


def _fake_s3(url="https://example.com/audio.mp3"):
    uploaded = {}
    def put_object(self, **kw):
        uploaded["key"] = kw["Key"]
    return type("S", (), {
        "put_object": put_object,
        "generate_presigned_url": lambda *a, **kw: url,
    })(), uploaded


def test_synthesize_returns_presigned_url(monkeypatch):
    import services.polly_tts as pt
    s3, uploaded = _fake_s3()
    monkeypatch.setattr(pt, "_polly_client", lambda: _fake_polly())
    monkeypatch.setattr(pt, "_s3_client", lambda: s3)
    url = pt.synthesize("<speak>Hello</speak>", session_id="sess-1")
    assert url == "https://example.com/audio.mp3"
    assert "sess-1" in uploaded["key"]


def test_polly_error_raises(monkeypatch):
    import services.polly_tts as pt
    bad_polly = type("P", (), {
        "synthesize_speech": lambda *a, **kw: (_ for _ in ()).throw(Exception("polly down"))
    })()
    monkeypatch.setattr(pt, "_polly_client", lambda: bad_polly)
    with pytest.raises(PollyError):
        pt.synthesize("<speak>Test</speak>")


def test_safe_synthesize_returns_none_on_error(monkeypatch):
    import services.polly_tts as pt
    monkeypatch.setattr(pt, "_polly_client", lambda: type("P", (), {
        "synthesize_speech": lambda *a, **kw: (_ for _ in ()).throw(Exception("down"))
    })())
    result = pt.safe_synthesize("<speak>Test</speak>")
    assert result is None
