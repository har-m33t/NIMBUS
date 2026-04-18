from common.schemas import InferMessage


def _valid_msg(**overrides):
    msg = {
        "action": "INFER",
        "sessionId": "11111111-1111-4111-8111-111111111111",
        "roomId": "room-1",
        "timestamp": "2026-04-18T12:00:00Z",
        "sequenceNumber": 1,
        "payload": {
            "keypoints": {"leftHand": [], "rightHand": [], "pose": []},
            "includeFaceCrop": False,
        },
    }
    msg.update(overrides)
    return msg


def test_infer_parses_minimal():
    m = InferMessage.model_validate(_valid_msg())
    assert m.sessionId.startswith("1111")
    assert m.payload.keypoints.leftHand == []


def test_face_crop_field_parsed():
    # faceCropBase64 is now modeled for Rekognition (PROTOCOLS.md §3.2).
    raw = _valid_msg()
    raw["payload"]["faceCropBase64"] = "base64data"
    m = InferMessage.model_validate(raw)
    assert m.payload.faceCropBase64 == "base64data"


def test_face_crop_field_optional():
    m = InferMessage.model_validate(_valid_msg())
    assert m.payload.faceCropBase64 is None


def test_landmark_range_enforced():
    raw = _valid_msg()
    raw["payload"]["keypoints"]["pose"] = [{"x": 1.5, "y": 0.5, "z": 0.0, "visibility": 1.0}]
    try:
        InferMessage.model_validate(raw)
    except Exception:
        return
    raise AssertionError("expected validation to fail on x>1.0")
