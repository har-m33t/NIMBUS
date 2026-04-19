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
from services.websocket import broadcast, post_to_connection

_log = logging.getLogger()
_log.setLevel(logging.DEBUG)

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

    _log.info(
        "JOIN_ROOM received sessionId=%s roomId=%s connectionId=%s body=%s",
        session_id, room_id, connection_id, json.dumps(body)[:500],
    )

    if not session_id:
        return bad_request("sessionId is required")
    if not _ROOM_ID_RE.match(room_id):
        return bad_request("roomId is required and must match [a-zA-Z0-9_-]{1,64}")

    try:
        # Remove any stale connectionIds for this session before writing the new one.
        # This handles React StrictMode double-mounts and reconnections where the old
        # WebSocket hasn't sent $disconnect yet but a new connection is already joining.
        all_peers = list(dynamo.list_room_peers(room_id))
        _log.info(
            "JOIN_ROOM roomId=%s peers_in_room=%d peers=%s",
            room_id, len(all_peers), str(all_peers),
        )

        stale = [
            p for p in all_peers
            if p.get("sessionId") == session_id and p["connectionId"] != connection_id
        ]
        if stale:
            _log.info(
                "JOIN_ROOM removing stale peers sessionId=%s stale=%s",
                session_id,
                json.dumps([p["connectionId"] for p in stale]),
            )
        for p in stale:
            dynamo.leave_room(room_id, p["connectionId"])
            _log.info("JOIN_ROOM cleaned stale conn=%s for session=%s", p["connectionId"], session_id)

        dynamo.join_room(room_id, connection_id, session_id)
        dynamo.update_session_room(session_id, room_id)
        dynamo.put_connection_index(connection_id, session_id, room_id)
        existing = [
            p for p in all_peers
            if p["connectionId"] != connection_id
            and p.get("sessionId") != session_id  # exclude stale same-session entries
        ]
        _log.info(
            "JOIN_ROOM existing_peers_for_ack sessionId=%s roomId=%s count=%d peers=%s",
            session_id, room_id, len(existing), str(existing),
        )
    except Exception:  # noqa: BLE001
        _log.exception("JOIN_ROOM failed for %s / %s", session_id, room_id)
        return server_error("Failed to join room")

    ack = {
        "type": "SIGNAL",
        "event": "JOIN_ROOM",
        "sessionId": session_id,
        "roomId": room_id,
        "payload": {"status": "joined", "peers": existing},
    }
    _log.info(
        "JOIN_ROOM sending ack connectionId=%s payload=%s",
        connection_id, json.dumps(ack)[:500],
    )
    ack_sent = post_to_connection(connection_id, ack)
    _log.info(
        "JOIN_ROOM ack delivery connectionId=%s success=%s",
        connection_id, ack_sent,
    )

    if existing:
        peer_joined_payload = {
            "type": "SIGNAL",
            "event": "PEER_JOINED",
            "sessionId": session_id,
            "roomId": room_id,
            "payload": {
                "connectionId": connection_id,
                "sessionId": session_id,
            },
        }
        broadcast_targets = [p["connectionId"] for p in existing]
        _log.info(
            "JOIN_ROOM broadcasting PEER_JOINED sessionId=%s roomId=%s targets=%s payload=%s",
            session_id, room_id,
            json.dumps(broadcast_targets),
            json.dumps(peer_joined_payload)[:500],
        )
        stale_after_broadcast = broadcast(broadcast_targets, peer_joined_payload)
        _log.info(
            "JOIN_ROOM PEER_JOINED broadcast done roomId=%s targets=%d stale=%s",
            room_id, len(broadcast_targets), str(stale_after_broadcast),
        )

    _log.info("JOIN_ROOM complete sessionId=%s roomId=%s peers=%d",
              session_id, room_id, len(existing))
    return ok()
