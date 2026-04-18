"""Caption fan-out Lambda (PROTOCOLS.md §7).

Invoked *directly* (synchronously or asynchronously) by Member 2's
ProcessFrame Lambda once a CAPTION payload is ready. It does NOT sit behind
an API Gateway route.

Expected input event shape:

    {
      "roomId": "<room-id>",
      "caption": {
        "type": "CAPTION",
        "sessionId": "<uuid-v4>",
        "timestamp": "<ISO-8601-UTC>",
        "sequenceNumber": 1024,
        "payload": { "text": "I am going to the store.", ... }
      }
    }

The `payload` is treated as opaque — this Lambda only validates
`caption.type == "CAPTION"` and the presence of `roomId`. Any additional
fields the upstream pipeline wants to include (emotion, audioUrl, latencyMs,
...) pass through unchanged. Removing an upstream feature requires no
changes to this handler.

Queries NIMBUS_PROD_Rooms for the target roomId and sends the caption to every
live connection. Stale connections (GoneException) are pruned from the table.
"""
from __future__ import annotations

import logging

from services import dynamo
from services.websocket import broadcast

_log = logging.getLogger()
_log.setLevel(logging.INFO)


def handler(event, _context):
    room_id = (event.get("roomId") or "").strip()
    caption = event.get("caption")

    if not room_id:
        _log.warning("Broadcast called without roomId; ignoring event")
        return {"ok": False, "error": "roomId is required"}
    if not isinstance(caption, dict) or caption.get("type") != "CAPTION":
        _log.warning("Broadcast called with malformed caption payload; ignoring")
        return {"ok": False, "error": "caption must be a CAPTION message"}

    connection_ids = list(dynamo.list_room_connections(room_id))
    if not connection_ids:
        _log.info("No active connections in room %s; caption dropped", room_id)
        return {"ok": True, "delivered": 0, "pruned": 0}

    stale = broadcast(connection_ids, caption)
    for cid in stale:
        try:
            dynamo.leave_room(room_id, cid)
            dynamo.delete_connection_index(cid)
        except Exception:  # noqa: BLE001 — best-effort cleanup
            _log.exception("Failed to prune stale connection %s", cid)

    delivered = len(connection_ids) - len(stale)
    _log.info(
        "Broadcast CAPTION roomId=%s delivered=%d pruned=%d",
        room_id,
        delivered,
        len(stale),
    )
    return {"ok": True, "delivered": delivered, "pruned": len(stale)}
