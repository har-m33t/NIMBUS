"""Handler-level tests for process_frame (letter/edge-inference mode — no SageMaker)."""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest


class _Ctx(SimpleNamespace):
    function_name = "NIMBUS_PROD_ProcessFrame"
    function_version = "$LATEST"
    memory_limit_in_mb = 1024
    invoked_function_arn = "arn:aws:lambda:us-east-1:000000000000:function:test"
    aws_request_id = "req-test"


CTX = _Ctx()
SESSION = "11111111-1111-4111-8111-111111111111"


def _event(seq: int = 1, token: str = "A", include_face: bool = False) -> dict:
    body: dict = {
        "action": "INFER",
        "sessionId": SESSION,
        "roomId": "room-1",
        "timestamp": "2026-04-18T12:00:00Z",
        "sequenceNumber": seq,
        "payload": {"token": token, "includeFaceCrop": include_face},
    }
    if include_face:
        body["payload"]["faceCropBase64"] = base64.b64encode(b"JPEG" * 100).decode()
    return {
        "requestContext": {
            "connectionId": "conn-abc",
            "domainName": "example.execute-api.us-east-1.amazonaws.com",
            "stage": "dev",
            "routeKey": "INFER",
        },
        "body": json.dumps(body),
    }


@pytest.fixture
def patched(monkeypatch):
    """Patch AWS-touching names. SageMaker is not used; clear dedup cache."""
    from handlers import process_frame
    from services import rekognition_emotion

    posts: list[dict] = []
    monkeypatch.setattr(
        process_frame, "post_to_connection",
        lambda event, conn, payload: posts.append({"conn": conn, "payload": payload}) or True,
    )
    monkeypatch.setattr(process_frame, "append_gloss",
                        lambda *a, **kw: {"glossBuffer": ["A"]})
    monkeypatch.setattr(rekognition_emotion, "detect_emotion",
                        lambda b: ("CALM", 1.0, {"CALM": 1.0}))
    monkeypatch.setattr(process_frame, "update_emotion", lambda sid, emo: None)
    process_frame._last_token.clear()
    process_frame._session_emotion.clear()
    yield posts


def test_gloss_event_emitted_on_success(patched):
    from handlers.process_frame import handler
    resp = handler(_event(seq=1, token="H"), CTX)
    assert resp["statusCode"] == 200
    types = [p["payload"]["type"] for p in patched]
    assert "GLOSS" in types
    gloss = next(p["payload"] for p in patched if p["payload"]["type"] == "GLOSS")
    assert gloss["payload"]["tokens"] == ["H"]
    assert gloss["payload"]["confidence"] == 1.0


def test_same_letter_twice_emits_gloss_only_once(patched):
    """Held-letter deduplication: second frame with same letter must not emit GLOSS."""
    from handlers.process_frame import handler
    handler(_event(seq=1, token="H"), CTX)
    handler(_event(seq=2, token="H"), CTX)
    gloss_events = [p for p in patched if p["payload"]["type"] == "GLOSS"]
    assert len(gloss_events) == 1, "GLOSS should only emit once per unique letter"


def test_emotion_emitted_every_10th_frame(patched):
    from handlers.process_frame import handler
    handler(_event(seq=10, token="A", include_face=True), CTX)
    types = [p["payload"]["type"] for p in patched]
    assert "EMOTION" in types
    emo = next(p["payload"] for p in patched if p["payload"]["type"] == "EMOTION")
    assert emo["payload"]["emotion"] in {
        "CALM", "HAPPY", "SAD", "ANGRY", "SURPRISED", "FEAR", "DISGUSTED", "CONFUSED"
    }
    assert "confidence" in emo["payload"]
    assert "allEmotions" in emo["payload"]


def test_no_emotion_on_non_tenth_frame(patched):
    from handlers.process_frame import handler
    handler(_event(seq=7, token="A"), CTX)
    types = [p["payload"]["type"] for p in patched]
    assert "EMOTION" not in types


def test_rekognition_called_with_face_crop(patched, monkeypatch):
    """On a 10th frame with face crop, detect_emotion receives the decoded bytes."""
    from services import rekognition_emotion

    rek_calls = []
    monkeypatch.setattr(rekognition_emotion, "detect_emotion",
                        lambda b: rek_calls.append(b) or ("HAPPY", 0.93, {"HAPPY": 0.93}))

    from handlers.process_frame import handler
    handler(_event(seq=10, token="A", include_face=True), CTX)

    assert rek_calls, "detect_emotion must be called on a face-crop 10th frame"
    assert isinstance(rek_calls[0], bytes), "must pass decoded bytes to Rekognition"


def test_rekognition_emotion_propagates_to_emotion_event(patched, monkeypatch):
    """Detected emotion label appears in the EMOTION event payload."""
    from services import rekognition_emotion

    monkeypatch.setattr(rekognition_emotion, "detect_emotion",
                        lambda b: ("HAPPY", 0.93, {"HAPPY": 0.93}))

    from handlers.process_frame import handler
    handler(_event(seq=10, token="A", include_face=True), CTX)

    emo = next(p["payload"] for p in patched if p["payload"]["type"] == "EMOTION")
    assert emo["payload"]["emotion"] == "HAPPY"
    assert emo["payload"]["allEmotions"]["HAPPY"] == pytest.approx(0.93)


def test_missing_token_returns_400():
    """INFER without token field returns 400."""
    from handlers.process_frame import handler
    bad_body = {
        "action": "INFER",
        "sessionId": SESSION,
        "roomId": "room-1",
        "timestamp": "2026-04-18T12:00:00Z",
        "sequenceNumber": 1,
        "payload": {},  # no token
    }
    event = {
        "requestContext": {"connectionId": "c", "routeKey": "INFER"},
        "body": json.dumps(bad_body),
    }
    resp = handler(event, CTX)
    assert resp["statusCode"] == 400


def test_invalid_schema_returns_400():
    from handlers.process_frame import handler
    bad = {"requestContext": {"connectionId": "c", "routeKey": "INFER"},
           "body": json.dumps({"action": "INFER"})}
    resp = handler(bad, CTX)
    assert resp["statusCode"] == 400


def test_non_infer_action_ignored():
    from handlers.process_frame import handler
    evt = {"requestContext": {"connectionId": "c", "routeKey": "$default"},
           "body": json.dumps({"action": "PING"})}
    resp = handler(evt, CTX)
    assert resp["statusCode"] == 200


# ── Edge-inference (browser ONNX token) tests ──────────────────────────────

def _edge_event(token: str, seq: int = 1) -> dict:
    body = {
        "action": "INFER",
        "sessionId": "22222222-2222-4222-8222-222222222222",
        "roomId": "room-edge",
        "timestamp": "2026-04-19T12:00:00Z",
        "sequenceNumber": seq,
        "payload": {"token": token},
    }
    return {
        "requestContext": {
            "connectionId": "conn-edge",
            "domainName": "example.execute-api.us-east-1.amazonaws.com",
            "stage": "dev",
            "routeKey": "INFER",
        },
        "body": json.dumps(body),
    }


@pytest.fixture
def patched_edge(monkeypatch):
    """Patch for edge-inference tests."""
    from handlers import process_frame

    posts: list[dict] = []
    monkeypatch.setattr(
        process_frame, "post_to_connection",
        lambda event, conn, payload: posts.append({"conn": conn, "payload": payload}) or True,
    )
    monkeypatch.setattr(process_frame, "append_gloss",
                        lambda *a, **kw: {"glossBuffer": ["W"]})
    process_frame._last_token.clear()
    process_frame._session_emotion.clear()
    yield posts


def test_edge_token_emits_gloss(patched_edge):
    """When payload.token is a letter, handler emits GLOSS with that letter."""
    from handlers.process_frame import handler
    resp = handler(_edge_event("W"), CTX)
    assert resp["statusCode"] == 200
    types = [p["payload"]["type"] for p in patched_edge]
    assert "GLOSS" in types
    gloss = next(p["payload"] for p in patched_edge if p["payload"]["type"] == "GLOSS")
    assert gloss["payload"]["tokens"] == ["W"]
    assert gloss["payload"]["confidence"] == 1.0


def test_edge_token_skips_sagemaker(patched_edge, monkeypatch):
    """Edge-inference mode must never invoke SageMaker endpoint."""
    from handlers import process_frame
    from services import sagemaker_inference

    invocations: list = []
    monkeypatch.setattr(sagemaker_inference, "invoke", lambda kp: invocations.append(kp) or {})

    resp = process_frame.handler(_edge_event("H"), CTX)
    assert resp["statusCode"] == 200
    assert not invocations, "SageMaker invoke must never be called in edge-inference mode"


def test_edge_token_appends_to_gloss_buffer(patched_edge, monkeypatch):
    """Edge token should be appended to the DDB gloss buffer."""
    from handlers import process_frame

    appended = []
    monkeypatch.setattr(
        process_frame, "append_gloss",
        lambda sid, tokens, cid, rid, emotion="CALM": appended.append(tokens) or {"glossBuffer": tokens},
    )

    process_frame.handler(_edge_event("B"), CTX)
    assert appended, "append_gloss must be called"
    assert appended[0] == ["B"]


def test_edge_token_schema_accepts_no_keypoints():
    """InferMessage should validate when payload has token but no keypoints."""
    from common.schemas import InferMessage
    msg = InferMessage.model_validate({
        "action": "INFER",
        "sessionId": "s1",
        "roomId": "r1",
        "timestamp": "2026-04-19T12:00:00Z",
        "sequenceNumber": 1,
        "payload": {"token": "H"},
    })
    assert msg.payload.token == "H"
    assert msg.payload.keypoints is None
