"""JOIN_ROOM signaling route.

Request body (PROTOCOLS.md §1.2 SIGNAL):
    {
      "action": "JOIN_ROOM",
      "sessionId": "<uuid-v4>",
      "roomId": "<room-id>",
      "payload": {}
    }

Writes a row into NIMBUS_PROD_Rooms and echoes a JOIN_ROOM ack back to the
caller so the UI can flip to "joined" state.
"""
from __future__ import annotations

import json
import logging
import re

from services import dynamo
from services.response import bad_request, ok, server_error
from services.websocket import post_to_connection

_log = logging.getLogger()
_log.setLevel(logging.INFO)

_ROOM_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


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

    if not session_id:
        return bad_request("sessionId is required")
    if not _ROOM_ID_RE.match(room_id):
        return bad_request("roomId is required and must match [a-zA-Z0-9_-]{1,64}")

    try:
        dynamo.join_room(room_id, connection_id, session_id)
        dynamo.update_session_room(session_id, room_id)
        dynamo.put_connection_index(connection_id, session_id, room_id)
    except Exception:  # noqa: BLE001
        _log.exception("JOIN_ROOM failed for %s / %s", session_id, room_id)
        return server_error("Failed to join room")

    ack = {
        "type": "SIGNAL",
        "event": "JOIN_ROOM",
        "sessionId": session_id,
        "roomId": room_id,
        "payload": {"status": "joined"},
    }
    post_to_connection(connection_id, ack)
    _log.info("JOIN_ROOM sessionId=%s roomId=%s", session_id, room_id)
    return ok()
