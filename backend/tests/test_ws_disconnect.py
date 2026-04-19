"""Coverage for handlers.ws_disconnect — cleanup paths + broadcast + tolerance of DDB errors."""
from __future__ import annotations

from unittest.mock import patch

from handlers import ws_disconnect


def _event() -> dict:
    return {"requestContext": {"connectionId": "conn-1"}}


def test_unknown_connection_is_noop():
    with patch.object(ws_disconnect, "dynamo") as mock_dyn:
        mock_dyn.get_connection_index.return_value = None

        resp = ws_disconnect.handler(_event(), None)

    assert resp["statusCode"] == 200
    mock_dyn.leave_room.assert_not_called()
    mock_dyn.delete_connection_index.assert_not_called()


def test_known_connection_with_room_cleans_up_both():
    with patch.object(ws_disconnect, "dynamo") as mock_dyn, \
            patch.object(ws_disconnect, "broadcast"):
        mock_dyn.get_connection_index.return_value = {
            "sessionIdRef": "abc",
            "roomId": "room-42",
        }
        mock_dyn.list_room_peers.return_value = []

        resp = ws_disconnect.handler(_event(), None)

    assert resp["statusCode"] == 200
    mock_dyn.leave_room.assert_called_once_with("room-42", "conn-1")
    mock_dyn.delete_connection_index.assert_called_once_with("conn-1")


def test_known_connection_without_room_skips_leave():
    with patch.object(ws_disconnect, "dynamo") as mock_dyn:
        mock_dyn.get_connection_index.return_value = {
            "sessionIdRef": "abc",
            "roomId": "",
        }

        resp = ws_disconnect.handler(_event(), None)

    assert resp["statusCode"] == 200
    mock_dyn.leave_room.assert_not_called()
    mock_dyn.delete_connection_index.assert_called_once_with("conn-1")


def test_leave_room_failure_still_deletes_index():
    with patch.object(ws_disconnect, "dynamo") as mock_dyn, \
            patch.object(ws_disconnect, "broadcast"):
        mock_dyn.get_connection_index.return_value = {
            "sessionIdRef": "abc",
            "roomId": "room-42",
        }
        mock_dyn.leave_room.side_effect = RuntimeError("ddb down")

        resp = ws_disconnect.handler(_event(), None)

    assert resp["statusCode"] == 200
    mock_dyn.delete_connection_index.assert_called_once_with("conn-1")


def test_delete_index_failure_is_swallowed():
    with patch.object(ws_disconnect, "dynamo") as mock_dyn:
        mock_dyn.get_connection_index.return_value = {
            "sessionIdRef": "abc",
            "roomId": "",
        }
        mock_dyn.delete_connection_index.side_effect = RuntimeError("ddb down")

        resp = ws_disconnect.handler(_event(), None)

    # Disconnect must always succeed — API GW won't retry it either way.
    assert resp["statusCode"] == 200


def test_disconnect_broadcasts_peer_left():
    with patch.object(ws_disconnect, "dynamo") as mock_dyn, \
            patch.object(ws_disconnect, "broadcast") as mock_bcast:
        mock_dyn.get_connection_index.return_value = {
            "sessionIdRef": "abc",
            "roomId": "room-42",
        }
        mock_dyn.list_room_peers.return_value = [
            {"connectionId": "conn-STAYS", "sessionId": "sess-STAYS"},
        ]

        resp = ws_disconnect.handler(_event(), None)

    assert resp["statusCode"] == 200
    bcast_args = mock_bcast.call_args.args
    assert list(bcast_args[0]) == ["conn-STAYS"]
    assert bcast_args[1]["event"] == "PEER_LEFT"
    assert bcast_args[1]["payload"]["connectionId"] == "conn-1"
