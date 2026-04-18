"""Coverage for handlers.leave_room — body validation + DDB + ack."""
from __future__ import annotations

import json

from unittest.mock import patch

from handlers import leave_room


def _event(body: dict | str | None) -> dict:
    return {
        "requestContext": {"connectionId": "conn-1"},
        "body": body if isinstance(body, str) else (json.dumps(body) if body else None),
    }


def test_happy_path_removes_room_and_acks():
    with patch.object(leave_room, "dynamo") as mock_dyn, \
            patch.object(leave_room, "post_to_connection") as mock_post:
        resp = leave_room.handler(
            _event({"sessionId": "abc", "roomId": "room-42"}),
            None,
        )

    assert resp["statusCode"] == 200
    mock_dyn.leave_room.assert_called_once_with("room-42", "conn-1")

    ack = mock_post.call_args.args[1]
    assert ack["type"] == "SIGNAL"
    assert ack["event"] == "LEAVE_ROOM"
    assert ack["payload"]["status"] == "left"


def test_missing_session_id_rejected():
    with patch.object(leave_room, "dynamo") as mock_dyn:
        resp = leave_room.handler(_event({"roomId": "room-42"}), None)
    assert resp["statusCode"] == 400
    mock_dyn.leave_room.assert_not_called()


def test_missing_room_id_rejected():
    with patch.object(leave_room, "dynamo") as mock_dyn:
        resp = leave_room.handler(_event({"sessionId": "abc"}), None)
    assert resp["statusCode"] == 400
    mock_dyn.leave_room.assert_not_called()


def test_malformed_body_rejected():
    with patch.object(leave_room, "dynamo") as mock_dyn:
        resp = leave_room.handler(_event("garbage"), None)
    assert resp["statusCode"] == 400
    mock_dyn.leave_room.assert_not_called()


def test_ddb_failure_returns_500_and_skips_ack():
    with patch.object(leave_room, "dynamo") as mock_dyn, \
            patch.object(leave_room, "post_to_connection") as mock_post:
        mock_dyn.leave_room.side_effect = RuntimeError("ddb down")
        resp = leave_room.handler(
            _event({"sessionId": "abc", "roomId": "room-42"}),
            None,
        )

    assert resp["statusCode"] == 500
    mock_post.assert_not_called()
