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


def test_face_crop_field_is_discarded():
    # C1: faceCropBase64 must be ignored — InferPayload has extra=ignore.
    raw = _valid_msg()
    raw["payload"]["faceCropBase64"] = "should-be-ignored"
    m = InferMessage.model_validate(raw)
    assert not hasattr(m.payload, "faceCropBase64")


def test_landmark_range_enforced():
    raw = _valid_msg()
    raw["payload"]["keypoints"]["pose"] = [{"x": 1.5, "y": 0.5, "z": 0.0, "visibility": 1.0}]
    try:
        InferMessage.model_validate(raw)
    except Exception:
        return
    raise AssertionError("expected validation to fail on x>1.0")
