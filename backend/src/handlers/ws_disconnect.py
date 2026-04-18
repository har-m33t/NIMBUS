"""$disconnect route handler.

Removes the caller from the Rooms table and the reverse-lookup index. The
Sessions STATE record is retained so Member 2's ProcessFrame Lambda can still
flush any in-flight gloss buffer; the table TTL (4h) will sweep it up later.
"""
from __future__ import annotations

import logging

from services import dynamo
from services.response import ok

_log = logging.getLogger()
_log.setLevel(logging.INFO)


def handler(event, _context):
    connection_id = event["requestContext"]["connectionId"]
    index = dynamo.get_connection_index(connection_id)

    if not index:
        _log.info("Disconnect for unknown connectionId=%s (already cleaned up)", connection_id)
        return ok()

    room_id = index.get("roomId") or ""
    if room_id:
        try:
            dynamo.leave_room(room_id, connection_id)
        except Exception:  # noqa: BLE001 — log and continue; don't block disconnect
            _log.exception("Failed to remove %s from room %s", connection_id, room_id)

    try:
        dynamo.delete_connection_index(connection_id)
    except Exception:  # noqa: BLE001
        _log.exception("Failed to delete connection index for %s", connection_id)

    _log.info(
        "Disconnected sessionId=%s connectionId=%s roomId=%s",
        index.get("sessionIdRef"),
        connection_id,
        room_id or "(none)",
    )
    return ok()
