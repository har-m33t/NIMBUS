"""$connect route handler.

The client opens the socket with sessionId (UUID v4) and roomId in the query
string. We persist the initial STATE record and a connectionId → session
reverse-lookup item so $disconnect can clean up in O(1).
"""
from __future__ import annotations

import logging
import re
from uuid import UUID

from services import dynamo
from services.response import bad_request, ok, server_error

_log = logging.getLogger()
_log.setLevel(logging.INFO)

_ROOM_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def _qs(event: dict) -> dict:
    return event.get("queryStringParameters") or {}


def _valid_uuid(value: str) -> bool:
    # UUID(value, version=4) coerces the version field instead of validating
    # it. Parse unconstrained and check the version explicitly.
    try:
        return UUID(value).version == 4
    except (ValueError, AttributeError, TypeError):
        return False


def handler(event, _context):
    connection_id = event["requestContext"]["connectionId"]
    params = _qs(event)
    session_id = (params.get("sessionId") or "").strip()
    room_id = (params.get("roomId") or "").strip()

    if not _valid_uuid(session_id):
        _log.warning("Rejecting connect — bad sessionId: %r", session_id)
        return bad_request("sessionId must be a UUID v4")
    if room_id and not _ROOM_ID_RE.match(room_id):
        _log.warning("Rejecting connect — bad roomId: %r", room_id)
        return bad_request("roomId contains invalid characters")

    try:
        dynamo.put_session_state(session_id, connection_id, room_id or None)
        dynamo.put_connection_index(connection_id, session_id, room_id or None)
    except Exception:  # noqa: BLE001 — surface as 500 so API GW rejects connect
        _log.exception("Failed to persist session state")
        return server_error("Failed to initialize session")

    _log.info(
        "Connected sessionId=%s connectionId=%s roomId=%s",
        session_id,
        connection_id,
        room_id or "(none)",
    )
    return ok({"sessionId": session_id, "connectionId": connection_id})
