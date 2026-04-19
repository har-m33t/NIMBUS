"""WEBRTC_SIGNAL route — relays SDP_OFFER, SDP_ANSWER, ICE_CANDIDATE from
one peer's connection to another peer's connection in the same room.

Request body:
    {
      "action":    "WEBRTC_SIGNAL",
      "signal":    "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE",
      "target":    "<connectionId of recipient>",
      "sessionId": "<sender's sessionId>",
      "roomId":    "<room>",
      "payload":   { "sdp": "..." } | { "candidate": {...} }
    }

The server rewrites the payload so the recipient learns who sent it:
    payload += {"from": <sender connId>, "fromSessionId": <sender sessionId>}

No DynamoDB read is required — the client has already learned the target's
connectionId via JOIN_ROOM peer list or PEER_JOINED broadcasts.
"""
from __future__ import annotations

import json
import logging

from services.response import bad_request, ok, server_error
from services.websocket import post_to_connection

_log = logging.getLogger()
_log.setLevel(logging.DEBUG)

_ALLOWED_SIGNALS = {"SDP_OFFER", "SDP_ANSWER", "ICE_CANDIDATE"}


def _parse_body(event: dict) -> dict:
    raw = event.get("body") or "{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def handler(event, _context):
    connection_id = event["requestContext"]["connectionId"]
    body = _parse_body(event)

    signal = (body.get("signal") or "").strip()
    target = (body.get("target") or "").strip()
    session_id = (body.get("sessionId") or "").strip()
    room_id = (body.get("roomId") or "").strip()
    payload = body.get("payload") or {}

    _log.info(
        "WEBRTC_SIGNAL received from connectionId=%s signal=%s target=%s sessionId=%s roomId=%s body=%s",
        connection_id, signal, target, session_id, room_id, json.dumps(body)[:500],
    )

    if signal not in _ALLOWED_SIGNALS:
        return bad_request(
            f"signal must be one of {sorted(_ALLOWED_SIGNALS)}, got '{signal}'"
        )

    if not target:
        return bad_request("target (connectionId of recipient) is required")

    if not session_id:
        return bad_request("sessionId is required")

    # Enrich the payload so the recipient knows who sent it
    relay = {
        "type": "SIGNAL",
        "event": signal,
        "sessionId": session_id,
        "roomId": room_id,
        "payload": {
            **payload,
            "from": connection_id,
            "fromSessionId": session_id,
        },
    }

    _log.info(
        "WEBRTC_SIGNAL relaying from=%s to=%s signal=%s relay=%s",
        connection_id, target, signal, json.dumps(relay)[:500],
    )

    try:
        sent = post_to_connection(target, relay)
        if not sent:
            _log.warning(
                "WEBRTC_SIGNAL target %s is gone (stale connection) — signal=%s from=%s payload=%s",
                target, signal, connection_id, json.dumps(relay)[:500],
            )
        else:
            _log.info(
                "WEBRTC_SIGNAL delivered signal=%s from=%s to=%s",
                signal, connection_id, target,
            )
    except Exception:  # noqa: BLE001
        _log.exception("WEBRTC_SIGNAL relay failed from %s to %s", connection_id, target)
        return server_error("Failed to relay signal")

    _log.info(
        "WEBRTC_SIGNAL %s from=%s to=%s room=%s sent=%s",
        signal, connection_id, target, room_id, sent,
    )
    return ok()
