"""Coverage for handlers.ws_connect — UUID validation, roomId regex, DDB errors."""
from __future__ import annotations

import json
from uuid import uuid4

from unittest.mock import patch

from handlers import ws_connect


def _event(session_id: str | None = None, room_id: str | None = None) -> dict:
    qs: dict[str, str] = {}
    if session_id is not None:
        qs["sessionId"] = session_id
    if room_id is not None:
        qs["roomId"] = room_id
    return {
        "requestContext": {"connectionId": "conn-1"},
        "queryStringParameters": qs or None,
    }


def test_accepts_valid_uuid_and_room_id():
    sid = str(uuid4())
    with patch.object(ws_connect, "dynamo") as mock_dyn:
        resp = ws_connect.handler(_event(sid, "room-42"), None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body == {"sessionId": sid, "connectionId": "conn-1", "userId": "anonymous"}

    mock_dyn.put_session_state.assert_called_once_with(sid, "conn-1", "room-42")
    mock_dyn.put_connection_index.assert_called_once_with("conn-1", sid, "room-42")


def test_accepts_missing_room_id():
    sid = str(uuid4())
    with patch.object(ws_connect, "dynamo") as mock_dyn:
        resp = ws_connect.handler(_event(sid), None)

    assert resp["statusCode"] == 200
    # When roomId is blank we pass None to downstream helpers.
    mock_dyn.put_session_state.assert_called_once_with(sid, "conn-1", None)
    mock_dyn.put_connection_index.assert_called_once_with("conn-1", sid, None)


def test_rejects_non_uuid_session_id():
    with patch.object(ws_connect, "dynamo") as mock_dyn:
        resp = ws_connect.handler(_event("not-a-uuid"), None)

    assert resp["statusCode"] == 400
    assert "UUID" in json.loads(resp["body"])["error"]
    mock_dyn.put_session_state.assert_not_called()


def test_rejects_uuid_v1_even_if_valid_format():
    # UUID v1 should fail the explicit version=4 check.
    import uuid as _uuid

    v1 = str(_uuid.uuid1())
    with patch.object(ws_connect, "dynamo") as mock_dyn:
        resp = ws_connect.handler(_event(v1), None)

    assert resp["statusCode"] == 400
    mock_dyn.put_session_state.assert_not_called()


def test_rejects_missing_session_id():
    with patch.object(ws_connect, "dynamo") as mock_dyn:
        resp = ws_connect.handler(_event(), None)

    assert resp["statusCode"] == 400
    mock_dyn.put_session_state.assert_not_called()


def test_rejects_invalid_room_id_characters():
    sid = str(uuid4())
    with patch.object(ws_connect, "dynamo") as mock_dyn:
        resp = ws_connect.handler(_event(sid, "room with space"), None)

    assert resp["statusCode"] == 400
    assert "roomId" in json.loads(resp["body"])["error"]
    mock_dyn.put_session_state.assert_not_called()


def test_rejects_oversized_room_id():
    sid = str(uuid4())
    with patch.object(ws_connect, "dynamo") as mock_dyn:
        resp = ws_connect.handler(_event(sid, "a" * 65), None)

    assert resp["statusCode"] == 400
    mock_dyn.put_session_state.assert_not_called()


def test_returns_500_on_ddb_failure():
    sid = str(uuid4())
    with patch.object(ws_connect, "dynamo") as mock_dyn:
        mock_dyn.put_session_state.side_effect = RuntimeError("boom")
        resp = ws_connect.handler(_event(sid, "room-42"), None)

    assert resp["statusCode"] == 500
    assert "initialize" in json.loads(resp["body"])["error"]


def test_null_query_string_parameters_is_treated_as_empty():
    # API Gateway sends queryStringParameters=null when none are present.
    event = {
        "requestContext": {"connectionId": "conn-1"},
        "queryStringParameters": None,
    }
    with patch.object(ws_connect, "dynamo") as mock_dyn:
        resp = ws_connect.handler(event, None)
    assert resp["statusCode"] == 400
    mock_dyn.put_session_state.assert_not_called()
