"""$disconnect route handler.

Removes the caller from the Rooms table, broadcasts PEER_LEFT to remaining
peers, and clears the reverse-lookup index. The Sessions STATE record is
retained so the gloss buffer can still drain; the table TTL (4h) sweeps it.
"""
from __future__ import annotations

import logging

from services import dynamo
from services.response import ok
from services.websocket import broadcast

_log = logging.getLogger()
_log.setLevel(logging.INFO)


def handler(event, _context):
    connection_id = event["requestContext"]["connectionId"]
    index = dynamo.get_connection_index(connection_id)

    if not index:
        _log.info("Disconnect for unknown connectionId=%s (already cleaned up)", connection_id)
        return ok()

    session_id = index.get("sessionIdRef") or ""
    room_id = index.get("roomId") or ""

    if room_id:
        try:
            dynamo.leave_room(room_id, connection_id)
            survivors = list(dynamo.list_room_peers(room_id))
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
        except Exception:  # noqa: BLE001 — log and continue; don't block disconnect
            _log.exception("Failed to remove %s from room %s", connection_id, room_id)

    try:
        dynamo.delete_connection_index(connection_id)
    except Exception:  # noqa: BLE001
        _log.exception("Failed to delete connection index for %s", connection_id)

    _log.info(
        "Disconnected sessionId=%s connectionId=%s roomId=%s",
        session_id,
        connection_id,
        room_id or "(none)",
    )
    return ok()
