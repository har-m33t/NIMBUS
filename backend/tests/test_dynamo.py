"""Coverage for services.dynamo — verifies put/get/delete shapes and pagination."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

from services import dynamo


def _has_valid_ttl(item: dict) -> bool:
    """TTL must be ~4h in the future per PROTOCOLS.md §2.1."""
    ttl = item.get("ttl")
    if not isinstance(ttl, int):
        return False
    delta = ttl - int(time.time())
    return 3.5 * 3600 < delta <= 4 * 3600 + 5


@patch.object(dynamo, "_sessions")
def test_put_session_state_writes_state_record(mock_sessions):
    dynamo.put_session_state("abc", "conn-1", room_id="room-42")

    mock_sessions.put_item.assert_called_once()
    item = mock_sessions.put_item.call_args.kwargs["Item"]
    assert item["sessionId"] == "abc"
    assert item["sk"] == "STATE"
    assert item["connectionId"] == "conn-1"
    assert item["roomId"] == "room-42"
    # Member 1 doesn't seed pipeline fields; verify they're absent so the
    # init stays narrow to its own responsibilities.
    assert "glossBuffer" not in item
    assert "lastEmotion" not in item
    assert _has_valid_ttl(item)


@patch.object(dynamo, "_sessions")
def test_put_session_state_accepts_no_room(mock_sessions):
    dynamo.put_session_state("abc", "conn-1")
    item = mock_sessions.put_item.call_args.kwargs["Item"]
    assert item["roomId"] == ""


@patch.object(dynamo, "_sessions")
def test_put_connection_index_uses_conn_prefix(mock_sessions):
    dynamo.put_connection_index("conn-1", "abc", "room-42")
    item = mock_sessions.put_item.call_args.kwargs["Item"]
    assert item["sessionId"] == "CONN#conn-1"
    assert item["sk"] == "INDEX"
    assert item["sessionIdRef"] == "abc"
    assert item["roomId"] == "room-42"


@patch.object(dynamo, "_sessions")
def test_get_connection_index_returns_item(mock_sessions):
    mock_sessions.get_item.return_value = {"Item": {"sessionIdRef": "abc"}}
    result = dynamo.get_connection_index("conn-1")
    mock_sessions.get_item.assert_called_once_with(
        Key={"sessionId": "CONN#conn-1", "sk": "INDEX"}
    )
    assert result == {"sessionIdRef": "abc"}


@patch.object(dynamo, "_sessions")
def test_get_connection_index_returns_none_when_missing(mock_sessions):
    mock_sessions.get_item.return_value = {}
    assert dynamo.get_connection_index("missing") is None


@patch.object(dynamo, "_sessions")
def test_delete_connection_index(mock_sessions):
    dynamo.delete_connection_index("conn-1")
    mock_sessions.delete_item.assert_called_once_with(
        Key={"sessionId": "CONN#conn-1", "sk": "INDEX"}
    )


@patch.object(dynamo, "_sessions")
def test_update_session_room_sets_room_and_ttl(mock_sessions):
    dynamo.update_session_room("abc", "room-42")
    kwargs = mock_sessions.update_item.call_args.kwargs
    assert kwargs["Key"] == {"sessionId": "abc", "sk": "STATE"}
    assert kwargs["ExpressionAttributeValues"][":r"] == "room-42"
    assert isinstance(kwargs["ExpressionAttributeValues"][":t"], int)


@patch.object(dynamo, "_rooms")
def test_join_room_writes_composite_key(mock_rooms):
    dynamo.join_room("room-42", "conn-1", "abc")
    item = mock_rooms.put_item.call_args.kwargs["Item"]
    assert item["roomId"] == "room-42"
    assert item["connectionId"] == "conn-1"
    assert item["sessionId"] == "abc"
    assert _has_valid_ttl(item)


@patch.object(dynamo, "_rooms")
def test_leave_room_deletes_composite_key(mock_rooms):
    dynamo.leave_room("room-42", "conn-1")
    mock_rooms.delete_item.assert_called_once_with(
        Key={"roomId": "room-42", "connectionId": "conn-1"}
    )


@patch.object(dynamo, "_rooms")
def test_list_room_connections_yields_all_pages(mock_rooms):
    mock_rooms.query.side_effect = [
        {
            "Items": [{"connectionId": "c1"}, {"connectionId": "c2"}],
            "LastEvaluatedKey": {"roomId": "room-42", "connectionId": "c2"},
        },
        {
            "Items": [{"connectionId": "c3"}],
        },
    ]

    result = list(dynamo.list_room_connections("room-42"))
    assert result == ["c1", "c2", "c3"]
    assert mock_rooms.query.call_count == 2
    # Second call must carry ExclusiveStartKey from the first page.
    second_call = mock_rooms.query.call_args_list[1].kwargs
    assert "ExclusiveStartKey" in second_call


@patch.object(dynamo, "_rooms")
def test_list_room_connections_handles_empty(mock_rooms):
    mock_rooms.query.return_value = {"Items": []}
    assert list(dynamo.list_room_connections("empty")) == []
