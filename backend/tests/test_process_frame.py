"""Handler-level Phase 1 tests. External AWS calls are monkeypatched."""
from __future__ import annotations

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


def _event(seq: int = 1, include_face: bool = False) -> dict:
    body = {
        "action": "INFER",
        "sessionId": "11111111-1111-4111-8111-111111111111",
        "roomId": "room-1",
        "timestamp": "2026-04-18T12:00:00Z",
        "sequenceNumber": seq,
        "payload": {
            "keypoints": {"leftHand": [], "rightHand": [], "pose": []},
            "includeFaceCrop": include_face,
        },
    }
    if include_face:
        body["payload"]["faceCropBase64"] = "AAA=" * 100
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
    """Patch all AWS-touching names used by the handler (patch at use site)."""
    from handlers import process_frame
    from services import sagemaker_inference, rekognition_emotion

    posts: list[dict] = []
    monkeypatch.setattr(process_frame, "post_to_connection",
                        lambda event, conn, payload: posts.append({"conn": conn, "payload": payload}) or True)
    monkeypatch.setattr(process_frame, "append_gloss",
                        lambda *a, **kw: {"glossBuffer": ["STORE"]})
    monkeypatch.setattr(sagemaker_inference, "is_in_service", lambda: True)
    monkeypatch.setattr(sagemaker_inference, "invoke",
                        lambda kp: {"tokens": ["STORE", "I", "GO"], "confidence": 0.87})
    monkeypatch.setattr(rekognition_emotion, "detect_emotion",
                        lambda b: ("CALM", 1.0, {"CALM": 1.0}))
    monkeypatch.setattr(process_frame, "update_emotion", lambda sid, emo: None)
    process_frame._cold_start_checked.clear()
    process_frame._session_emotion.clear()
    yield posts


def test_gloss_event_emitted_on_success(patched):
    from handlers.process_frame import handler
    resp = handler(_event(seq=1), CTX)
    assert resp["statusCode"] == 200
    types = [p["payload"]["type"] for p in patched]
    assert "GLOSS" in types
    gloss = next(p["payload"] for p in patched if p["payload"]["type"] == "GLOSS")
    assert gloss["payload"]["tokens"] == ["STORE", "I", "GO"]


def test_emotion_emitted_every_10th_frame(patched):
    from handlers.process_frame import handler
    handler(_event(seq=10), CTX)
    types = [p["payload"]["type"] for p in patched]
    assert "EMOTION" in types
    emo = next(p["payload"] for p in patched if p["payload"]["type"] == "EMOTION")
    assert emo["payload"]["emotion"] in {"CALM", "HAPPY", "SAD", "ANGRY",
                                         "SURPRISED", "FEAR", "DISGUSTED", "CONFUSED"}
    assert "confidence" in emo["payload"]
    assert "allEmotions" in emo["payload"]


def test_no_emotion_on_non_tenth_frame(patched):
    from handlers.process_frame import handler
    handler(_event(seq=7), CTX)
    types = [p["payload"]["type"] for p in patched]
    assert "EMOTION" not in types


def test_rekognition_called_with_face_crop(patched, monkeypatch):
    """On a 10th frame with face crop, detect_emotion receives the decoded bytes."""
    import base64
    from services import rekognition_emotion

    rek_calls = []
    monkeypatch.setattr(rekognition_emotion, "detect_emotion",
                        lambda b: rek_calls.append(b) or ("HAPPY", 0.93, {"HAPPY": 0.93}))

    from handlers.process_frame import handler
    handler(_event(seq=10, include_face=True), CTX)

    assert rek_calls, "detect_emotion must be called on a face-crop 10th frame"
    assert isinstance(rek_calls[0], bytes), "must pass decoded bytes to Rekognition"


def test_rekognition_emotion_propagates_to_emotion_event(patched, monkeypatch):
    """Detected emotion label appears in the EMOTION event payload."""
    from services import rekognition_emotion

    monkeypatch.setattr(rekognition_emotion, "detect_emotion",
                        lambda b: ("HAPPY", 0.93, {"HAPPY": 0.93}))

    from handlers.process_frame import handler
    handler(_event(seq=10, include_face=True), CTX)

    emo = next(p["payload"] for p in patched if p["payload"]["type"] == "EMOTION")
    assert emo["payload"]["emotion"] == "HAPPY"
    assert emo["payload"]["allEmotions"]["HAPPY"] == pytest.approx(0.93)


def test_face_crop_never_reaches_sagemaker(patched, monkeypatch):
    """face crop bytes must not be forwarded to SageMaker (C1 partial)."""
    from services import sagemaker_inference
    seen = {}
    def fake_invoke(kp):
        assert not hasattr(kp, "faceCropBase64")
        seen["called"] = True
        return {"tokens": ["X"], "confidence": 0.5}
    monkeypatch.setattr(sagemaker_inference, "invoke", fake_invoke)

    from handlers.process_frame import handler
    handler(_event(seq=1, include_face=True), CTX)
    assert seen["called"] is True


def test_sagemaker_error_emits_error_event(patched, monkeypatch):
    from services import sagemaker_inference
    from common.errors import SageMakerError
    def fail(_):
        raise SageMakerError("endpoint timed out")
    monkeypatch.setattr(sagemaker_inference, "invoke", fail)

    from handlers.process_frame import handler
    resp = handler(_event(seq=1), CTX)
    assert resp["statusCode"] == 200
    err = next(p["payload"] for p in patched if p["payload"]["type"] == "ERROR")
    assert err["payload"]["code"] == "SAGEMAKER_INFERENCE_FAILED"
    assert err["payload"]["glossFallback"] == "[UNKNOWN_SIGN]"


def test_endpoint_warming_signal_on_cold_start(monkeypatch):
    from services import sagemaker_inference
    from handlers import process_frame

    posts: list[dict] = []
    monkeypatch.setattr(process_frame, "post_to_connection",
                        lambda e, c, p: posts.append(p) or True)
    monkeypatch.setattr(process_frame, "append_gloss", lambda *a, **kw: {})
    monkeypatch.setattr(sagemaker_inference, "is_in_service", lambda: False)
    process_frame._cold_start_checked.clear()

    resp = process_frame.handler(_event(seq=1), CTX)
    assert resp["statusCode"] == 200
    signals = [p for p in posts if p["type"] == "SIGNAL"]
    assert signals and signals[0]["event"] == "ENDPOINT_WARMING"


def test_invalid_schema_returns_400(monkeypatch):
    from handlers.process_frame import handler
    bad = {"requestContext": {"connectionId": "c", "routeKey": "INFER"},
           "body": json.dumps({"action": "INFER"})}
    resp = handler(bad, CTX)
    assert resp["statusCode"] == 400


def test_non_infer_action_ignored(monkeypatch):
    from handlers.process_frame import handler
    evt = {"requestContext": {"connectionId": "c", "routeKey": "$default"},
           "body": json.dumps({"action": "PING"})}
    resp = handler(evt, CTX)
    assert resp["statusCode"] == 200


# ── Edge-inference (browser ONNX token) tests ──────────────────────────────


def _edge_event(token: str, seq: int = 1) -> dict:
    """Build an INFER event with a direct gloss token (no keypoints)."""
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
    """Patch for edge-inference tests — SageMaker should never be called."""
    from handlers import process_frame
    from services import sagemaker_inference

    posts: list[dict] = []
    monkeypatch.setattr(process_frame, "post_to_connection",
                        lambda event, conn, payload: posts.append({"conn": conn, "payload": payload}) or True)
    monkeypatch.setattr(process_frame, "append_gloss",
                        lambda *a, **kw: {"glossBuffer": ["WATER"]})

    # SageMaker should NOT be called — make it explode if it is
    def sagemaker_boom(_):
        raise AssertionError("SageMaker must not be called in edge-inference mode")
    monkeypatch.setattr(sagemaker_inference, "invoke", sagemaker_boom)
    monkeypatch.setattr(sagemaker_inference, "is_in_service", lambda: (_ for _ in ()).throw(
        AssertionError("is_in_service must not be called in edge-inference mode")))

    process_frame._cold_start_checked.clear()
    process_frame._session_emotion.clear()
    yield posts


def test_edge_token_emits_gloss(patched_edge):
    """When payload.token is set, handler emits GLOSS with the token."""
    from handlers.process_frame import handler
    resp = handler(_edge_event("WATER"), CTX)
    assert resp["statusCode"] == 200
    types = [p["payload"]["type"] for p in patched_edge]
    assert "GLOSS" in types
    gloss = next(p["payload"] for p in patched_edge if p["payload"]["type"] == "GLOSS")
    assert gloss["payload"]["tokens"] == ["WATER"]
    assert gloss["payload"]["confidence"] == 1.0


def test_edge_token_skips_sagemaker(patched_edge):
    """Edge-inference mode must not invoke SageMaker at all."""
    from handlers.process_frame import handler
    # If SageMaker is called, the patched_edge fixture will raise AssertionError
    resp = handler(_edge_event("HELLO"), CTX)
    assert resp["statusCode"] == 200


def test_edge_token_appends_to_gloss_buffer(patched_edge, monkeypatch):
    """Edge token should be appended to the DDB gloss buffer."""
    from handlers import process_frame

    appended = []
    monkeypatch.setattr(process_frame, "append_gloss",
                        lambda sid, tokens, cid, rid, emotion="CALM": appended.append(tokens) or {"glossBuffer": tokens})

    process_frame.handler(_edge_event("BOOK"), CTX)
    assert appended, "append_gloss must be called"
    assert appended[0] == ["BOOK"]


def test_edge_token_schema_accepts_no_keypoints():
    """InferMessage should validate when payload has token but no keypoints."""
    from common.schemas import InferMessage
    msg = InferMessage.model_validate({
        "action": "INFER",
        "sessionId": "s1",
        "roomId": "r1",
        "timestamp": "2026-04-19T12:00:00Z",
        "sequenceNumber": 1,
        "payload": {"token": "HELLO"},
    })
    assert msg.payload.token == "HELLO"
    assert msg.payload.keypoints is None
