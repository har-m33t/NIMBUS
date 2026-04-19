"""Coverage for handlers.webrtc_signal — relay logic + validation."""
from __future__ import annotations

import json
from unittest.mock import patch

from handlers import webrtc_signal


def _event(body: dict, conn_id: str = "conn-SENDER") -> dict:
    return {
        "requestContext": {"connectionId": conn_id},
        "body": json.dumps(body),
    }


def test_relays_sdp_offer_to_target():
    with patch.object(webrtc_signal, "post_to_connection") as mock_post:
        mock_post.return_value = True
        resp = webrtc_signal.handler(
            _event({
                "signal": "SDP_OFFER",
                "target": "conn-RECEIVER",
                "sessionId": "sess-1",
                "roomId": "room-1",
                "payload": {"sdp": "v=0..."},
            }),
            None,
        )

    assert resp["statusCode"] == 200
    call_args = mock_post.call_args.args
    assert call_args[0] == "conn-RECEIVER"
    relay = call_args[1]
    assert relay["event"] == "SDP_OFFER"
    assert relay["payload"]["sdp"] == "v=0..."
    assert relay["payload"]["from"] == "conn-SENDER"
    assert relay["payload"]["fromSessionId"] == "sess-1"


def test_relays_ice_candidate():
    with patch.object(webrtc_signal, "post_to_connection") as mock_post:
        mock_post.return_value = True
        resp = webrtc_signal.handler(
            _event({
                "signal": "ICE_CANDIDATE",
                "target": "conn-RECEIVER",
                "sessionId": "sess-1",
                "roomId": "room-1",
                "payload": {"candidate": {"candidate": "a]...", "sdpMid": "0"}},
            }),
            None,
        )

    assert resp["statusCode"] == 200
    relay = mock_post.call_args.args[1]
    assert relay["event"] == "ICE_CANDIDATE"
    assert relay["payload"]["from"] == "conn-SENDER"


def test_rejects_unknown_signal_type():
    with patch.object(webrtc_signal, "post_to_connection") as mock_post:
        resp = webrtc_signal.handler(
            _event({
                "signal": "INVALID_TYPE",
                "target": "conn-RECEIVER",
                "sessionId": "sess-1",
                "roomId": "room-1",
                "payload": {},
            }),
            None,
        )

    assert resp["statusCode"] == 400
    mock_post.assert_not_called()


def test_rejects_missing_target():
    with patch.object(webrtc_signal, "post_to_connection") as mock_post:
        resp = webrtc_signal.handler(
            _event({
                "signal": "SDP_OFFER",
                "target": "",
                "sessionId": "sess-1",
                "roomId": "room-1",
                "payload": {"sdp": "v=0..."},
            }),
            None,
        )

    assert resp["statusCode"] == 400
    mock_post.assert_not_called()


def test_rejects_missing_session_id():
    with patch.object(webrtc_signal, "post_to_connection") as mock_post:
        resp = webrtc_signal.handler(
            _event({
                "signal": "SDP_OFFER",
                "target": "conn-RECEIVER",
                "sessionId": "",
                "roomId": "room-1",
                "payload": {"sdp": "v=0..."},
            }),
            None,
        )

    assert resp["statusCode"] == 400
    mock_post.assert_not_called()


def test_stale_target_returns_200():
    """If the target connection is gone, relay returns 200 (best-effort)."""
    with patch.object(webrtc_signal, "post_to_connection") as mock_post:
        mock_post.return_value = False  # GoneException
        resp = webrtc_signal.handler(
            _event({
                "signal": "SDP_ANSWER",
                "target": "conn-GONE",
                "sessionId": "sess-1",
                "roomId": "room-1",
                "payload": {"sdp": "v=0..."},
            }),
            None,
        )

    assert resp["statusCode"] == 200
