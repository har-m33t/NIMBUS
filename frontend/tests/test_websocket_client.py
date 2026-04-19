from __future__ import annotations

import time

import numpy as np

from aws.websocket_client import WebSocketClient


def test_build_connect_url_preserves_existing_query() -> None:
    client = WebSocketClient(
        "wss://example.execute-api.us-east-1.amazonaws.com/dev?foo=bar",
        session_id="sid",
        room_id="room",
    )

    url = client._build_connect_url()

    assert "foo=bar" in url
    assert "sessionId=sid" in url
    assert "roomId=room" in url


def test_coerce_protocol_frame_uses_last_active_row() -> None:
    buffer = np.zeros((3, 258), dtype=np.float32)
    buffer[1, 0] = 0.25
    buffer[2, 5] = 0.75

    frame = WebSocketClient._coerce_protocol_frame(buffer)

    assert frame.shape == (258,)
    assert frame[5] == 0.75


def test_serialize_keypoints_matches_protocol_shape() -> None:
    frame = np.zeros(258, dtype=np.float32)
    frame[0:3] = [0.1, 0.2, -0.3]
    frame[126:130] = [0.4, 0.5, -0.2, 0.9]

    payload = WebSocketClient._serialize_keypoints(frame)

    assert len(payload["leftHand"]) == 21
    assert payload["rightHand"] == []
    assert len(payload["pose"]) == 33
    assert np.isclose(payload["leftHand"][0]["x"], 0.1)
    assert np.isclose(payload["leftHand"][0]["y"], 0.2)
    assert np.isclose(payload["leftHand"][0]["z"], -0.3)
    assert np.isclose(payload["pose"][0]["x"], 0.4)
    assert np.isclose(payload["pose"][0]["y"], 0.5)
    assert np.isclose(payload["pose"][0]["z"], -0.2)
    assert np.isclose(payload["pose"][0]["visibility"], 0.9)


def test_serialize_keypoints_keeps_zero_pose_entries_for_protocol() -> None:
    payload = WebSocketClient._serialize_keypoints(np.zeros(258, dtype=np.float32))

    assert payload["leftHand"] == []
    assert payload["rightHand"] == []
    assert len(payload["pose"]) == 33
    assert payload["pose"][0] == {"x": 0.0, "y": 0.0, "z": 0.0, "visibility": 0.0}


def test_serialize_keypoints_sanitizes_non_finite_values() -> None:
    frame = np.zeros(258, dtype=np.float32)
    frame[0:3] = [np.nan, np.inf, -np.inf]

    payload = WebSocketClient._serialize_keypoints(frame)

    assert payload["leftHand"][0] == {"x": 0.0, "y": 0.0, "z": 0.0}


def test_normalize_event_adds_latency_for_gloss() -> None:
    client = WebSocketClient("wss://example.test/ws", session_id="sid", room_id="room")
    client._pending_sent_at[7] = time.monotonic() - 0.12

    event = client._normalize_event(
        {
            "type": "GLOSS",
            "sequenceNumber": 7,
            "payload": {"tokens": ["HELLO"], "confidence": 0.8},
        }
    )

    assert event["payload"]["tokens"] == ["HELLO"]
    assert event["payload"]["confidence"] == 0.8
    assert event["payload"]["latencyMs"] >= 100


def test_send_infer_rejects_bad_shapes_without_throwing() -> None:
    client = WebSocketClient("wss://example.test/ws", session_id="sid", room_id="room")
    client.connect = lambda: True

    sequence_number = client.send_infer(np.zeros((4, 10), dtype=np.float32))

    assert sequence_number is None
    assert "Expected shape" in (client.last_error or "")
