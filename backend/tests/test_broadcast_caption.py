"""Coverage for handlers.broadcast_caption — fan-out, empty rooms, stale pruning."""
from __future__ import annotations

from unittest.mock import patch

from handlers import broadcast_caption


def _caption(**extra_payload) -> dict:
    """Build a minimal CAPTION message. `extra_payload` lets a test verify
    that arbitrary upstream fields (emotion, audioUrl, ...) pass through
    without the handler caring what's in them."""
    return {
        "type": "CAPTION",
        "sessionId": "abc",
        "timestamp": "2026-04-18T00:00:00Z",
        "sequenceNumber": 1024,
        "payload": {"text": "Hello, world.", **extra_payload},
    }


def test_missing_room_id_returns_error():
    resp = broadcast_caption.handler({"caption": _caption()}, None)
    assert resp["ok"] is False
    assert "roomId" in resp["error"]


def test_missing_caption_returns_error():
    resp = broadcast_caption.handler({"roomId": "room-42"}, None)
    assert resp["ok"] is False


def test_caption_with_wrong_type_rejected():
    bad = _caption()
    bad["type"] = "GLOSS"
    resp = broadcast_caption.handler({"roomId": "room-42", "caption": bad}, None)
    assert resp["ok"] is False


def test_empty_room_returns_zero_delivered():
    with patch.object(broadcast_caption, "dynamo") as mock_dyn, \
            patch.object(broadcast_caption, "broadcast") as mock_broadcast:
        mock_dyn.list_room_connections.return_value = iter([])
        resp = broadcast_caption.handler(
            {"roomId": "room-42", "caption": _caption()},
            None,
        )

    assert resp == {"ok": True, "delivered": 0, "pruned": 0}
    mock_broadcast.assert_not_called()


def test_all_connections_delivered():
    with patch.object(broadcast_caption, "dynamo") as mock_dyn, \
            patch.object(broadcast_caption, "broadcast") as mock_broadcast:
        mock_dyn.list_room_connections.return_value = iter(["c1", "c2", "c3"])
        mock_broadcast.return_value = []

        resp = broadcast_caption.handler(
            {"roomId": "room-42", "caption": _caption()},
            None,
        )

    assert resp == {"ok": True, "delivered": 3, "pruned": 0}
    mock_broadcast.assert_called_once()
    call_args = mock_broadcast.call_args.args
    assert call_args[0] == ["c1", "c2", "c3"]
    assert call_args[1]["type"] == "CAPTION"


def test_payload_is_forwarded_opaquely():
    """Handler must not inspect payload fields — whatever Member 2 puts in the
    caption payload (with or without emotion/audioUrl) goes through unchanged.
    This locks in the contract so removing any upstream feature is safe.
    """
    extras = {"emotion": "HAPPY", "audioUrl": "https://x/a.mp3", "latencyMs": 321}
    caption_with = _caption(**extras)
    caption_without = _caption()

    for payload in (caption_with, caption_without):
        with patch.object(broadcast_caption, "dynamo") as mock_dyn, \
                patch.object(broadcast_caption, "broadcast") as mock_broadcast:
            mock_dyn.list_room_connections.return_value = iter(["c1"])
            mock_broadcast.return_value = []
            resp = broadcast_caption.handler(
                {"roomId": "room-42", "caption": payload},
                None,
            )
            assert resp["ok"] is True
            forwarded = mock_broadcast.call_args.args[1]
            assert forwarded == payload  # byte-for-byte pass-through


def test_stale_connections_are_pruned():
    with patch.object(broadcast_caption, "dynamo") as mock_dyn, \
            patch.object(broadcast_caption, "broadcast") as mock_broadcast:
        mock_dyn.list_room_connections.return_value = iter(["c1", "c2", "c3", "c4"])
        mock_broadcast.return_value = ["c2", "c4"]

        resp = broadcast_caption.handler(
            {"roomId": "room-42", "caption": _caption()},
            None,
        )

    assert resp == {"ok": True, "delivered": 2, "pruned": 2}
    mock_dyn.leave_room.assert_any_call("room-42", "c2")
    mock_dyn.leave_room.assert_any_call("room-42", "c4")
    mock_dyn.delete_connection_index.assert_any_call("c2")
    mock_dyn.delete_connection_index.assert_any_call("c4")


def test_prune_failure_does_not_abort_remaining_cleanup():
    with patch.object(broadcast_caption, "dynamo") as mock_dyn, \
            patch.object(broadcast_caption, "broadcast") as mock_broadcast:
        mock_dyn.list_room_connections.return_value = iter(["c1", "c2"])
        mock_broadcast.return_value = ["c1", "c2"]
        # First leave_room call blows up; second must still run.
        mock_dyn.leave_room.side_effect = [RuntimeError("ddb"), None]

        resp = broadcast_caption.handler(
            {"roomId": "room-42", "caption": _caption()},
            None,
        )

    assert resp == {"ok": True, "delivered": 0, "pruned": 2}
    assert mock_dyn.leave_room.call_count == 2
