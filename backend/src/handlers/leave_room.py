"""LEAVE_ROOM signaling route.

Body schema is identical to JOIN_ROOM. Removes the Rooms row and echoes a
LEAVE_ROOM ack. If the connection later disconnects it's a no-op.
"""
from __future__ import annotations

import json
import logging

from services import dynamo
from services.response import bad_request, ok, server_error
from services.websocket import broadcast, post_to_connection

_log = logging.getLogger()
_log.setLevel(logging.INFO)


def _parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def handler(event, _context):
    connection_id = event["requestContext"]["connectionId"]
    body = _parse_body(event)

    session_id = (body.get("sessionId") or "").strip()
    room_id = (body.get("roomId") or "").strip()

    if not session_id or not room_id:
        return bad_request("sessionId and roomId are required")

    try:
        dynamo.leave_room(room_id, connection_id)
        survivors = list(dynamo.list_room_peers(room_id))
    except Exception:  # noqa: BLE001
        _log.exception("LEAVE_ROOM failed for %s / %s", session_id, room_id)
        return server_error("Failed to leave room")

    ack = {
        "type": "SIGNAL",
        "event": "LEAVE_ROOM",
        "sessionId": session_id,
        "roomId": room_id,
        "payload": {"status": "left"},
    }
    post_to_connection(connection_id, ack)

    if survivors:
        broadcast(
            [p["connectionId"] for p in survivors],
            {
                "type": "SIGNAL",
                "event": "PEER_LEFT",
                "sessionId": session_id,
                "roomId": room_id,
                "payload": {
                    "connectionId": connection_id,
                    "sessionId": session_id,
                },
            },
        )

    _log.info("LEAVE_ROOM sessionId=%s roomId=%s", session_id, room_id)
    return ok()
