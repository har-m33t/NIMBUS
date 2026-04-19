"""Coverage for handlers.join_room — body parsing, DDB writes, ack message."""
from __future__ import annotations

import json
from uuid import uuid4

from unittest.mock import patch

from handlers import join_room


def _event(body: dict | str | None, conn_id: str = "conn-1") -> dict:
    return {
        "requestContext": {"connectionId": conn_id},
        "body": body if isinstance(body, str) else (json.dumps(body) if body else None),
    }


def test_happy_path_writes_room_and_sends_ack():
    sid = str(uuid4())
    with patch.object(join_room, "dynamo") as mock_dyn, \
            patch.object(join_room, "post_to_connection") as mock_post, \
            patch.object(join_room, "broadcast"):
        mock_dyn.list_room_peers.return_value = iter([])
        resp = join_room.handler(
            _event({"sessionId": sid, "roomId": "room-42"}),
            None,
        )

    assert resp["statusCode"] == 200
    mock_dyn.join_room.assert_called_once_with("room-42", "conn-1", sid)
    mock_dyn.update_session_room.assert_called_once_with(sid, "room-42")
    mock_dyn.put_connection_index.assert_called_once_with("conn-1", sid, "room-42")

    ack = mock_post.call_args.args[1]
    assert ack["type"] == "SIGNAL"
    assert ack["event"] == "JOIN_ROOM"
    assert ack["sessionId"] == sid
    assert ack["roomId"] == "room-42"
    assert ack["payload"]["status"] == "joined"
    assert ack["payload"]["peers"] == []


def test_missing_session_id_is_rejected():
    with patch.object(join_room, "dynamo") as mock_dyn, \
            patch.object(join_room, "post_to_connection") as mock_post:
        resp = join_room.handler(_event({"roomId": "room-42"}), None)

    assert resp["statusCode"] == 400
    assert "sessionId" in json.loads(resp["body"])["error"]
    mock_dyn.join_room.assert_not_called()
    mock_post.assert_not_called()


def test_missing_room_id_is_rejected():
    with patch.object(join_room, "dynamo") as mock_dyn:
        resp = join_room.handler(_event({"sessionId": "abc"}), None)
    assert resp["statusCode"] == 400
    mock_dyn.join_room.assert_not_called()


def test_invalid_room_id_characters_rejected():
    with patch.object(join_room, "dynamo") as mock_dyn:
        resp = join_room.handler(
            _event({"sessionId": "abc", "roomId": "has spaces"}),
            None,
        )
    assert resp["statusCode"] == 400
    mock_dyn.join_room.assert_not_called()


def test_malformed_body_treated_as_missing_fields():
    with patch.object(join_room, "dynamo") as mock_dyn:
        resp = join_room.handler(_event("{not json"), None)
    assert resp["statusCode"] == 400
    mock_dyn.join_room.assert_not_called()


def test_missing_body_treated_as_missing_fields():
    with patch.object(join_room, "dynamo") as mock_dyn:
        resp = join_room.handler(_event(None), None)
    assert resp["statusCode"] == 400
    mock_dyn.join_room.assert_not_called()


def test_ddb_failure_returns_500_and_skips_ack():
    with patch.object(join_room, "dynamo") as mock_dyn, \
            patch.object(join_room, "post_to_connection") as mock_post:
        mock_dyn.join_room.side_effect = RuntimeError("ddb down")
        resp = join_room.handler(
            _event({"sessionId": "abc", "roomId": "room-42"}),
            None,
        )

    assert resp["statusCode"] == 500
    mock_post.assert_not_called()


def test_join_returns_existing_peers_and_broadcasts():
    sid = "11111111-1111-4111-8111-111111111111"
    with patch.object(join_room, "dynamo") as mock_dyn, \
            patch.object(join_room, "post_to_connection") as mock_post, \
            patch.object(join_room, "broadcast") as mock_bcast:
        mock_dyn.list_room_peers.return_value = iter([
            {"connectionId": "conn-OLD", "sessionId": "sess-OLD"},
            {"connectionId": "conn-NEW", "sessionId": sid},
        ])
        resp = join_room.handler(
            _event({"sessionId": sid, "roomId": "room-42"}, conn_id="conn-NEW"),
            None,
        )

    assert resp["statusCode"] == 200
    # JOIN_ROOM ack sent to the joiner with peer list
    ack = mock_post.call_args.args[1]
    assert ack["event"] == "JOIN_ROOM"
    assert ack["payload"]["peers"] == [
        {"connectionId": "conn-OLD", "sessionId": "sess-OLD"},
    ]
    # PEER_JOINED broadcast to the other peers
    bcast_args = mock_bcast.call_args.args
    assert list(bcast_args[0]) == ["conn-OLD"]
    assert bcast_args[1]["event"] == "PEER_JOINED"
    assert bcast_args[1]["payload"] == {
        "connectionId": "conn-NEW",
        "sessionId": sid,
    }
