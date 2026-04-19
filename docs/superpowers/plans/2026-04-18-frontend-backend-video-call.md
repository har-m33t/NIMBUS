# Frontend ↔ Backend Video-Call Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the React web frontend to the AWS WebSocket backend so two users on different devices can join the same room and see each other's live webcam video inside the existing Session page UI.

**Architecture:** Thin P2P WebRTC (`RTCPeerConnection` + public STUN) with signaling relayed through the *already-deployed* AWS API Gateway WebSocket API. We add ONE new route (`WEBRTC_SIGNAL`) plus peer-presence broadcasts from the existing `JOIN_ROOM` / `LEAVE_ROOM` / `$disconnect` handlers. No mediasoup EC2 deploy required for MVP; the mediasoup path in `infrastructure/mediasoup/` is preserved for a future >2-peer phase.

**Tech Stack:** React 19 + Vite + TypeScript + framer-motion (existing); native `RTCPeerConnection` (no mediasoup-client for now); AWS SAM (Python 3.13 Lambdas, API Gateway WebSocket v2, DynamoDB); Cognito for auth token on `$connect`.

**Non-goals (defer to future plan):**
- Captions/GLOSS pipeline end-to-end (ProcessFrame Lambda already tested; wiring it into the web `CaptionBar` is out of scope here).
- Screen share.
- TURN server (public STUN is usually enough for hackathon demos on open networks; if peer-behind-symmetric-NAT blocks, note the limitation).
- Mediasoup SFU deploy (good for >2 peers; design preserved).

---

## File Structure (what each file will own)

**Backend (new / modified)**

| File | Role |
|---|---|
| `backend/src/handlers/webrtc_signal.py` | **NEW** — Relay `SDP_OFFER`, `SDP_ANSWER`, `ICE_CANDIDATE` from one connection to another in the same room. |
| `backend/src/handlers/join_room.py` | **MODIFY** — After writing the Rooms row, return the list of existing peers to the joiner and broadcast `PEER_JOINED` to the rest. |
| `backend/src/handlers/leave_room.py` | **MODIFY** — Broadcast `PEER_LEFT` to remaining peers. |
| `backend/src/handlers/ws_disconnect.py` | **MODIFY** — On unclean disconnect, broadcast `PEER_LEFT` too. |
| `backend/src/common/schemas.py` | **MODIFY** — Add `PEER_JOINED`, `PEER_LEFT` to `SignalEvent` literal. |
| `backend/template.yaml` | **MODIFY** — Add `WEBRTC_SIGNAL` route + integration + Lambda function. |
| `backend/tests/handlers/test_webrtc_signal.py` | **NEW** — Unit tests for relay logic. |
| `backend/tests/handlers/test_join_room.py` | **MODIFY** — Add coverage for peer-list return + broadcast. |

**Web (new / modified)**

| File | Role |
|---|---|
| `web/src/config/ws.ts` | **NEW** — Centralized WS URL helpers + env var reading. |
| `web/src/hooks/useSessionSocket.ts` | **NEW** — Auth-aware WebSocket connection + typed send/recv, reconnect. |
| `web/src/hooks/useWebRTC.ts` | **NEW** — Map of `RTCPeerConnection` per remote peer; wires to signaling. |
| `web/src/hooks/useLocalMedia.ts` | **NEW** — `getUserMedia` wrapper with error states. |
| `web/src/components/session/RemoteVideo.tsx` | **NEW** — `<video>` element bound to a `MediaStream`. |
| `web/src/components/session/VideoFeed.tsx` | **MODIFY** — Render real `MediaStream` (not placeholder). |
| `web/src/components/session/ParticipantsPanel.tsx` | **MODIFY** — Embed `RemoteVideo` thumbnails next to each participant. |
| `web/src/pages/Session.tsx` | **MODIFY** — Replace demo data with hooks; plumb `localStream` + `remotePeers`. |
| `web/.env.example` | **NEW** — Document required Vite env vars. |

---

## Phase 0 — Baseline & Shared Prep

### Task 0.1: Confirm dev environment works

**Files:** none

- [ ] **Step 1: Verify backend builds and tests pass**

Run:
```bash
cd backend && pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests/ -q
```
Expected: all existing tests PASS. If any fail, STOP and fix before continuing.

- [ ] **Step 2: Verify web app runs**

Run:
```bash
cd web && npm install && npm run dev
```
Expected: Vite prints a `http://localhost:5173` URL; opening it shows the sign-in page.
Kill the dev server when verified.

- [ ] **Step 3: Verify mediasoup Node tests pass (sanity)**

Run:
```bash
cd infrastructure/mediasoup && npm install && npm test
```
Expected: `node --test` reports 0 failures. (We're not deploying it, but keep it green.)

- [ ] **Step 4: Commit nothing yet** — baseline verification only.

---

## Phase 1 — Backend: Peer Presence & WebRTC Signaling Relay

### Task 1.1: Add PEER_JOINED / PEER_LEFT to the SignalEvent literal

**Files:**
- Modify: `backend/src/common/schemas.py:13-16`

- [ ] **Step 1: Edit the `SignalEvent` literal**

Change:
```python
SignalEvent = Literal[
    "JOIN_ROOM", "LEAVE_ROOM", "ICE_CANDIDATE",
    "SDP_OFFER", "SDP_ANSWER", "NEW_CAPTION", "ENDPOINT_WARMING",
]
```
to:
```python
SignalEvent = Literal[
    "JOIN_ROOM", "LEAVE_ROOM", "ICE_CANDIDATE",
    "SDP_OFFER", "SDP_ANSWER", "NEW_CAPTION", "ENDPOINT_WARMING",
    "PEER_JOINED", "PEER_LEFT",
]
```

- [ ] **Step 2: Run tests to confirm nothing broke**

Run: `cd backend && python -m pytest tests/ -q`
Expected: all pass (purely additive change).

- [ ] **Step 3: Commit**

```bash
cd backend
git add src/common/schemas.py
git commit -m "feat(schemas): add PEER_JOINED and PEER_LEFT signal events"
```

---

### Task 1.2: Extend dynamo.py to list peers with their session/display data

**Files:**
- Modify: `backend/src/services/dynamo.py` (append a new function)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/services/test_dynamo_peers.py`:
```python
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_rooms_table():
    with patch("services.dynamo._rooms") as table:
        yield table


def test_list_room_peers_returns_connection_and_session(mock_rooms_table):
    from services import dynamo

    mock_rooms_table.query.return_value = {
        "Items": [
            {"connectionId": "conn-A", "sessionId": "sess-A"},
            {"connectionId": "conn-B", "sessionId": "sess-B"},
        ],
        "LastEvaluatedKey": None,
    }
    result = list(dynamo.list_room_peers("room-1"))
    assert result == [
        {"connectionId": "conn-A", "sessionId": "sess-A"},
        {"connectionId": "conn-B", "sessionId": "sess-B"},
    ]
```

- [ ] **Step 2: Run the test — expect FAIL**

Run: `cd backend && python -m pytest tests/services/test_dynamo_peers.py -v`
Expected: FAIL with `AttributeError: module 'services.dynamo' has no attribute 'list_room_peers'`.

- [ ] **Step 3: Implement `list_room_peers`**

Append to `backend/src/services/dynamo.py`:
```python
def list_room_peers(room_id: str) -> Iterable[dict]:
    """Yield every peer currently in a room, each as {connectionId, sessionId}.

    Like list_room_connections but also exposes sessionId so the web client
    can render stable peer identifiers across reconnects.
    """
    last_key = None
    while True:
        kwargs = {
            "KeyConditionExpression": "roomId = :r",
            "ExpressionAttributeValues": {":r": room_id},
            "ProjectionExpression": "connectionId, sessionId",
        }
        if last_key is not None:
            kwargs["ExclusiveStartKey"] = last_key
        resp = _rooms.query(**kwargs)
        for item in resp.get("Items", []):
            yield {
                "connectionId": item["connectionId"],
                "sessionId": item.get("sessionId", ""),
            }
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            return
```

- [ ] **Step 4: Run the test — expect PASS**

Run: `cd backend && python -m pytest tests/services/test_dynamo_peers.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd backend
git add src/services/dynamo.py tests/services/test_dynamo_peers.py
git commit -m "feat(dynamo): list_room_peers projects connectionId + sessionId"
```

---

### Task 1.3: Extend `join_room` handler to return peer list and broadcast PEER_JOINED

**Files:**
- Modify: `backend/src/handlers/join_room.py`
- Modify: `backend/tests/handlers/test_join_room.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create/extend `backend/tests/handlers/test_join_room.py`:
```python
import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", "sess-t")
    monkeypatch.setenv("ROOMS_TABLE", "rooms-t")
    monkeypatch.setenv("WEBSOCKET_ENDPOINT", "https://example")


def _event(body: dict, conn_id="conn-NEW"):
    return {
        "requestContext": {"connectionId": conn_id},
        "body": json.dumps(body),
    }


def test_join_returns_existing_peers_and_broadcasts(env):
    with patch("handlers.join_room.dynamo") as dyn, \
         patch("handlers.join_room.post_to_connection") as pst, \
         patch("handlers.join_room.broadcast") as bcast:
        dyn.list_room_peers.return_value = [
            {"connectionId": "conn-OLD", "sessionId": "sess-OLD"},
        ]
        from handlers import join_room
        resp = join_room.handler(
            _event({"sessionId": "11111111-1111-4111-8111-111111111111",
                    "roomId": "demo-room"}),
            None,
        )

    assert resp["statusCode"] == 200
    # JOIN_ROOM ack sent to the joiner with peer list
    ack_call = pst.call_args_list[0]
    assert ack_call.args[0] == "conn-NEW"
    ack_payload = ack_call.args[1]
    assert ack_payload["event"] == "JOIN_ROOM"
    assert ack_payload["payload"]["peers"] == [
        {"connectionId": "conn-OLD", "sessionId": "sess-OLD"},
    ]
    # PEER_JOINED broadcast to the other peers
    bcast_args = bcast.call_args.args
    assert list(bcast_args[0]) == ["conn-OLD"]
    assert bcast_args[1]["event"] == "PEER_JOINED"
    assert bcast_args[1]["payload"] == {
        "connectionId": "conn-NEW",
        "sessionId": "11111111-1111-4111-8111-111111111111",
    }
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd backend && python -m pytest tests/handlers/test_join_room.py -v`
Expected: FAIL (handler still sends old-shape ack with no peer list and no broadcast).

- [ ] **Step 3: Update `join_room.py`**

Replace the body of `backend/src/handlers/join_room.py` `handler` after the `update_session_room` call with:
```python
    try:
        dynamo.join_room(room_id, connection_id, session_id)
        dynamo.update_session_room(session_id, room_id)
        dynamo.put_connection_index(connection_id, session_id, room_id)
        existing = [
            p for p in dynamo.list_room_peers(room_id)
            if p["connectionId"] != connection_id
        ]
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
    post_to_connection(connection_id, ack)

    if existing:
        broadcast(
            [p["connectionId"] for p in existing],
            {
                "type": "SIGNAL",
                "event": "PEER_JOINED",
                "sessionId": session_id,
                "roomId": room_id,
                "payload": {
                    "connectionId": connection_id,
                    "sessionId": session_id,
                },
            },
        )

    _log.info("JOIN_ROOM sessionId=%s roomId=%s peers=%d",
              session_id, room_id, len(existing))
    return ok()
```

And at the top of the file add the `broadcast` import:
```python
from services.websocket import broadcast, post_to_connection
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd backend && python -m pytest tests/handlers/test_join_room.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd backend
git add src/handlers/join_room.py tests/handlers/test_join_room.py
git commit -m "feat(join_room): return existing peers and broadcast PEER_JOINED"
```

---

### Task 1.4: Broadcast PEER_LEFT from `leave_room` and `ws_disconnect`

**Files:**
- Modify: `backend/src/handlers/leave_room.py`
- Modify: `backend/src/handlers/ws_disconnect.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/handlers/test_leave_room_broadcast.py`:
```python
import json
from unittest.mock import patch


def _event(body, conn_id="conn-GONE"):
    return {"requestContext": {"connectionId": conn_id}, "body": json.dumps(body)}


def test_leave_broadcasts_peer_left(monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", "sess")
    monkeypatch.setenv("ROOMS_TABLE", "rooms")
    monkeypatch.setenv("WEBSOCKET_ENDPOINT", "https://example")
    with patch("handlers.leave_room.dynamo") as dyn, \
         patch("handlers.leave_room.post_to_connection") as pst, \
         patch("handlers.leave_room.broadcast") as bcast:
        dyn.list_room_peers.return_value = [
            {"connectionId": "conn-STAYS", "sessionId": "sess-STAYS"},
        ]
        from handlers import leave_room
        leave_room.handler(
            _event({"sessionId": "11111111-1111-4111-8111-111111111111",
                    "roomId": "demo"}),
            None,
        )

    bcast_args = bcast.call_args.args
    assert list(bcast_args[0]) == ["conn-STAYS"]
    assert bcast_args[1]["event"] == "PEER_LEFT"
    assert bcast_args[1]["payload"]["connectionId"] == "conn-GONE"
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd backend && python -m pytest tests/handlers/test_leave_room_broadcast.py -v`
Expected: FAIL.

- [ ] **Step 3: Update `leave_room.py`**

Replace its `handler` body with:
```python
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
                "payload": {"connectionId": connection_id, "sessionId": session_id},
            },
        )

    _log.info("LEAVE_ROOM sessionId=%s roomId=%s", session_id, room_id)
    return ok()
```

And ensure this import at the top:
```python
from services.websocket import broadcast, post_to_connection
```

- [ ] **Step 4: Update `ws_disconnect.py` to do the same broadcast**

Replace `backend/src/handlers/ws_disconnect.py` with:
```python
"""$disconnect route handler.

Removes the caller from the Rooms table, broadcasts PEER_LEFT to remaining
peers, and clears the reverse-lookup index. The Sessions STATE record is
retained so the gloss buffer can still drain; the table TTL (4h) sweeps it.
"""
from __future__ import annotations

import logging
import os

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
        except Exception:  # noqa: BLE001
            _log.exception("Failed to remove %s from room %s", connection_id, room_id)

        try:
            survivors = list(dynamo.list_room_peers(room_id))
        except Exception:  # noqa: BLE001
            _log.exception("Failed to list survivors in room %s", room_id)
            survivors = []

        if survivors:
            try:
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
            except Exception:  # noqa: BLE001
                _log.exception("Failed to broadcast PEER_LEFT for %s", connection_id)

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
```

Also: the `WSDisconnectFunction` in `template.yaml` must have `WEBSOCKET_ENDPOINT` so `broadcast()` can resolve the Management API endpoint. Add under its `Properties`:
```yaml
      Environment:
        Variables:
          WEBSOCKET_ENDPOINT: !Sub https://${WebSocketApi}.execute-api.${AWS::Region}.amazonaws.com/${StageName}
```

- [ ] **Step 5: Run all backend tests — expect PASS**

Run: `cd backend && python -m pytest tests/ -q`
Expected: 0 failures.

- [ ] **Step 6: Commit**

```bash
cd backend
git add src/handlers/leave_room.py src/handlers/ws_disconnect.py tests/handlers/test_leave_room_broadcast.py
git commit -m "feat(rooms): broadcast PEER_LEFT on leave + disconnect"
```

---

### Task 1.5: Create the WEBRTC_SIGNAL relay Lambda

**Files:**
- Create: `backend/src/handlers/webrtc_signal.py`
- Create: `backend/tests/handlers/test_webrtc_signal.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/handlers/test_webrtc_signal.py`:
```python
import json
from unittest.mock import patch


def _event(body, conn_id="conn-SENDER"):
    return {"requestContext": {"connectionId": conn_id}, "body": json.dumps(body)}


def test_relays_sdp_offer_to_target(monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", "sess")
    monkeypatch.setenv("ROOMS_TABLE", "rooms")
    monkeypatch.setenv("WEBSOCKET_ENDPOINT", "https://example")
    with patch("handlers.webrtc_signal.post_to_connection") as pst:
        from handlers import webrtc_signal
        resp = webrtc_signal.handler(
            _event({
                "sessionId": "11111111-1111-4111-8111-111111111111",
                "roomId": "demo",
                "target": "conn-RECEIVER",
                "signal": "SDP_OFFER",
                "payload": {"sdp": "v=0..."},
            }),
            None,
        )
    assert resp["statusCode"] == 200
    pst.assert_called_once()
    target_cid, payload = pst.call_args.args
    assert target_cid == "conn-RECEIVER"
    assert payload["type"] == "SIGNAL"
    assert payload["event"] == "SDP_OFFER"
    assert payload["payload"] == {
        "sdp": "v=0...",
        "from": "conn-SENDER",
        "fromSessionId": "11111111-1111-4111-8111-111111111111",
    }


def test_rejects_unknown_signal_type(monkeypatch):
    monkeypatch.setenv("SESSIONS_TABLE", "sess")
    monkeypatch.setenv("ROOMS_TABLE", "rooms")
    monkeypatch.setenv("WEBSOCKET_ENDPOINT", "https://example")
    from handlers import webrtc_signal
    resp = webrtc_signal.handler(
        _event({
            "sessionId": "11111111-1111-4111-8111-111111111111",
            "roomId": "demo",
            "target": "conn-RECEIVER",
            "signal": "NONSENSE",
            "payload": {},
        }),
        None,
    )
    assert resp["statusCode"] == 400
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `cd backend && python -m pytest tests/handlers/test_webrtc_signal.py -v`
Expected: FAIL with ModuleNotFoundError.

- [ ] **Step 3: Implement the handler**

Create `backend/src/handlers/webrtc_signal.py`:
```python
"""WEBRTC_SIGNAL route — relays SDP_OFFER, SDP_ANSWER, ICE_CANDIDATE from
one peer's connection to another peer's connection in the same room.

Request body:
    {
      "action":    "WEBRTC_SIGNAL",
      "sessionId": "<uuid-v4>",
      "roomId":    "<room-id>",
      "target":    "<connectionId of recipient>",
      "signal":    "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE",
      "payload":   { ... opaque to the server ... }
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
_log.setLevel(logging.INFO)

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

    session_id = (body.get("sessionId") or "").strip()
    room_id = (body.get("roomId") or "").strip()
    target = (body.get("target") or "").strip()
    signal = (body.get("signal") or "").strip()
    payload = body.get("payload") or {}

    if not session_id or not room_id or not target:
        return bad_request("sessionId, roomId, target are required")
    if signal not in _ALLOWED_SIGNALS:
        return bad_request(f"signal must be one of {sorted(_ALLOWED_SIGNALS)}")
    if not isinstance(payload, dict):
        return bad_request("payload must be an object")

    outgoing = {
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

    try:
        delivered = post_to_connection(target, outgoing)
    except Exception:  # noqa: BLE001
        _log.exception("WEBRTC_SIGNAL relay failed %s→%s", connection_id, target)
        return server_error("Relay failed")

    if not delivered:
        _log.info("WEBRTC_SIGNAL target %s is gone; dropping %s", target, signal)
    return ok()
```

- [ ] **Step 4: Run test — expect PASS**

Run: `cd backend && python -m pytest tests/handlers/test_webrtc_signal.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd backend
git add src/handlers/webrtc_signal.py tests/handlers/test_webrtc_signal.py
git commit -m "feat(webrtc): add WEBRTC_SIGNAL relay for SDP + ICE"
```

---

### Task 1.6: Wire the WEBRTC_SIGNAL route into `template.yaml`

**Files:**
- Modify: `backend/template.yaml`

- [ ] **Step 1: Add the route, integration, function, permission, log group**

Insert after the `LeaveRoomRoute` / `LeaveRoomIntegration` block (around line 232–238). Add a new route:

```yaml
  WebRtcSignalRoute:
    Type: AWS::ApiGatewayV2::Route
    Properties:
      ApiId: !Ref WebSocketApi
      RouteKey: WEBRTC_SIGNAL
      AuthorizationType: NONE
      Target: !Sub integrations/${WebRtcSignalIntegration}

  WebRtcSignalIntegration:
    Type: AWS::ApiGatewayV2::Integration
    Properties:
      ApiId: !Ref WebSocketApi
      IntegrationType: AWS_PROXY
      IntegrationUri: !Sub arn:${AWS::Partition}:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${WebRtcSignalFunction.Arn}/invocations
```

Add to `ApiDeployment.DependsOn`:
```yaml
      - WebRtcSignalRoute
```

Add a function next to `LeaveRoomFunction` (around line 443–459):
```yaml
  WebRtcSignalFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: NIMBUS_PROD_WebRtcSignal
      Handler: handlers.webrtc_signal.handler
      Role: !GetAtt LambdaExecutionRole.Arn
      MemorySize: 128
      Description: Relay WebRTC SDP and ICE between peers in the same room.
      Environment:
        Variables:
          WEBSOCKET_ENDPOINT: !Sub https://${WebSocketApi}.execute-api.${AWS::Region}.amazonaws.com/${StageName}

  WebRtcSignalPermission:
    Type: AWS::Lambda::Permission
    Properties:
      FunctionName: !Ref WebRtcSignalFunction
      Action: lambda:InvokeFunction
      Principal: apigateway.amazonaws.com
      SourceArn: !Sub arn:${AWS::Partition}:execute-api:${AWS::Region}:${AWS::AccountId}:${WebSocketApi}/*

  WebRtcSignalLogGroup:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: /aws/lambda/NIMBUS_PROD_WebRtcSignal
      RetentionInDays: 14
```

- [ ] **Step 2: Validate the template**

Run: `cd backend && sam validate --lint`
Expected: `template.yaml is a valid SAM Template`.

- [ ] **Step 3: Commit**

```bash
cd backend
git add template.yaml
git commit -m "feat(sam): add WEBRTC_SIGNAL route + Lambda wiring"
```

---

### Task 1.7: Ensure JoinRoom / LeaveRoom Lambdas have `WEBSOCKET_ENDPOINT` (already present, verify)

**Files:**
- Modify: `backend/template.yaml` (verify only, no changes expected)

- [ ] **Step 1: Verify env vars**

Open `backend/template.yaml` and confirm `JoinRoomFunction` and `LeaveRoomFunction` each have `Environment.Variables.WEBSOCKET_ENDPOINT` set (they do, at lines ~432 and ~449). If absent, copy the shape from `BroadcastCaptionFunction`.

No commit needed if the template is already correct.

---

### Task 1.8: Deploy the backend

**Files:** none (CI-like step)

- [ ] **Step 1: Build**

Run: `cd backend && sam build`
Expected: "Build Succeeded".

- [ ] **Step 2: Deploy**

Run: `cd backend && sam deploy`
Expected: CloudFormation update succeeds; output shows `WebSocketURL: wss://<id>.execute-api.us-east-1.amazonaws.com/prod`.

**Record** the `WebSocketURL` and the `CognitoUserPoolClientId` / `CognitoUserPoolId` outputs — Phase 2 needs them.

- [ ] **Step 3: Smoke-test `WEBRTC_SIGNAL` with `wscat`**

Install `wscat` if needed: `npm install -g wscat`.

Get a Cognito ID token (from an existing test user or the web app after sign-in).
Run:
```bash
wscat -c "wss://<id>.execute-api.us-east-1.amazonaws.com/prod?token=<ID_TOKEN>&sessionId=<UUIDv4>&roomId=demo"
> {"action":"JOIN_ROOM","sessionId":"<UUIDv4>","roomId":"demo"}
```
Expected: server sends back `{"type":"SIGNAL","event":"JOIN_ROOM","payload":{"status":"joined","peers":[]}}`.

Open a SECOND `wscat` with a different sessionId — the first should now receive `PEER_JOINED`.

---

## Phase 2 — Web: WebSocket Client Hook

### Task 2.1: Document env vars and add WS URL helpers

**Files:**
- Create: `web/.env.example`
- Create: `web/src/config/ws.ts`

- [ ] **Step 1: Write `.env.example`**

Create `web/.env.example`:
```
# Copy to .env.local and fill in values from `sam deploy` outputs.
VITE_COGNITO_USER_POOL_ID=us-east-1_xxxxxxxxx
VITE_COGNITO_CLIENT_ID=xxxxxxxxxxxxxxxxxxxxxxxxxx
VITE_COGNITO_REGION=us-east-1
VITE_NIMBUS_WS_URL=wss://xxxxxxxxxx.execute-api.us-east-1.amazonaws.com/prod
```

- [ ] **Step 2: Create `web/src/config/ws.ts`**

```ts
export const WS_CONFIG = {
  url: import.meta.env.VITE_NIMBUS_WS_URL || "",
} as const;

export function buildWsUrl(params: {
  token: string;
  sessionId: string;
  roomId: string;
}): string {
  if (!WS_CONFIG.url) {
    throw new Error("VITE_NIMBUS_WS_URL is not set — copy .env.example to .env.local");
  }
  const u = new URL(WS_CONFIG.url);
  u.searchParams.set("token", params.token);
  u.searchParams.set("sessionId", params.sessionId);
  u.searchParams.set("roomId", params.roomId);
  return u.toString();
}
```

- [ ] **Step 3: Commit**

```bash
cd web
git add .env.example src/config/ws.ts
git commit -m "feat(web): add WS config helper and env template"
```

---

### Task 2.2: Create `useSessionSocket` hook

**Files:**
- Create: `web/src/hooks/useSessionSocket.ts`

- [ ] **Step 1: Write the hook**

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import { buildWsUrl } from "../config/ws.ts";

export type InboundSignal =
  | { type: "SIGNAL"; event: "JOIN_ROOM"; roomId: string; payload: { status: string; peers: PeerInfo[] } }
  | { type: "SIGNAL"; event: "PEER_JOINED"; roomId: string; payload: PeerInfo }
  | { type: "SIGNAL"; event: "PEER_LEFT"; roomId: string; payload: PeerInfo }
  | { type: "SIGNAL"; event: "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE"; roomId: string; payload: SdpIceFromRelay }
  | { type: "ERROR"; payload: { code: string; message?: string } };

export interface PeerInfo {
  connectionId: string;
  sessionId: string;
}

export interface SdpIceFromRelay {
  from: string;
  fromSessionId: string;
  // SDP_OFFER / SDP_ANSWER carry { sdp }; ICE_CANDIDATE carries { candidate, sdpMid, sdpMLineIndex }
  sdp?: string;
  candidate?: RTCIceCandidateInit;
}

export type SocketStatus = "idle" | "connecting" | "open" | "closed" | "error";

export interface UseSessionSocketOptions {
  token: string | null;
  sessionId: string;
  roomId: string | null;
  onMessage: (msg: InboundSignal) => void;
}

export function useSessionSocket({ token, sessionId, roomId, onMessage }: UseSessionSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<SocketStatus>("idle");
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!token || !roomId) return;
    const url = buildWsUrl({ token, sessionId, roomId });
    const ws = new WebSocket(url);
    wsRef.current = ws;
    setStatus("connecting");

    ws.onopen = () => {
      setStatus("open");
      ws.send(JSON.stringify({ action: "JOIN_ROOM", sessionId, roomId }));
    };
    ws.onmessage = (ev) => {
      try {
        const parsed = JSON.parse(ev.data);
        onMessageRef.current(parsed as InboundSignal);
      } catch {
        // ignore malformed frames
      }
    };
    ws.onclose = () => setStatus("closed");
    ws.onerror = () => setStatus("error");

    return () => {
      if (ws.readyState === WebSocket.OPEN) {
        try {
          ws.send(JSON.stringify({ action: "LEAVE_ROOM", sessionId, roomId }));
        } catch {
          // connection already gone — ignore
        }
      }
      ws.close();
      wsRef.current = null;
    };
  }, [token, sessionId, roomId]);

  const send = useCallback((payload: object) => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return false;
    ws.send(JSON.stringify(payload));
    return true;
  }, []);

  const sendWebRtcSignal = useCallback(
    (target: string, signal: "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE", payload: object) => {
      if (!roomId) return false;
      return send({
        action: "WEBRTC_SIGNAL",
        sessionId,
        roomId,
        target,
        signal,
        payload,
      });
    },
    [send, sessionId, roomId],
  );

  return { status, send, sendWebRtcSignal };
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd web
git add src/hooks/useSessionSocket.ts
git commit -m "feat(web): add useSessionSocket hook"
```

---

## Phase 3 — Web: Local Media & WebRTC Peer Management

### Task 3.1: Create `useLocalMedia` hook

**Files:**
- Create: `web/src/hooks/useLocalMedia.ts`

- [ ] **Step 1: Write the hook**

```ts
import { useEffect, useState } from "react";

export type MediaError = "permission-denied" | "no-device" | "unknown" | null;

export function useLocalMedia(enabled: boolean) {
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [error, setError] = useState<MediaError>(null);

  useEffect(() => {
    if (!enabled) return;
    let mounted = true;
    let active: MediaStream | null = null;

    navigator.mediaDevices
      .getUserMedia({
        video: { width: 1280, height: 720, frameRate: 30 },
        audio: true,
      })
      .then((s) => {
        if (!mounted) {
          s.getTracks().forEach((t) => t.stop());
          return;
        }
        active = s;
        setStream(s);
        setError(null);
      })
      .catch((err: DOMException) => {
        if (!mounted) return;
        if (err.name === "NotAllowedError") setError("permission-denied");
        else if (err.name === "NotFoundError") setError("no-device");
        else setError("unknown");
      });

    return () => {
      mounted = false;
      if (active) active.getTracks().forEach((t) => t.stop());
      setStream(null);
    };
  }, [enabled]);

  return { stream, error };
}
```

- [ ] **Step 2: Verify types**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd web
git add src/hooks/useLocalMedia.ts
git commit -m "feat(web): add useLocalMedia hook"
```

---

### Task 3.2: Create `useWebRTC` hook

**Files:**
- Create: `web/src/hooks/useWebRTC.ts`

- [ ] **Step 1: Write the hook**

```ts
import { useCallback, useEffect, useRef, useState } from "react";
import type { PeerInfo, SdpIceFromRelay } from "./useSessionSocket.ts";

export interface RemotePeer {
  connectionId: string;
  sessionId: string;
  stream: MediaStream;
}

const ICE_SERVERS: RTCIceServer[] = [
  { urls: ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"] },
];

export interface UseWebRTCArgs {
  localStream: MediaStream | null;
  sendWebRtcSignal: (
    target: string,
    signal: "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE",
    payload: object,
  ) => boolean;
}

export function useWebRTC({ localStream, sendWebRtcSignal }: UseWebRTCArgs) {
  const pcsRef = useRef<Map<string, RTCPeerConnection>>(new Map());
  const [peers, setPeers] = useState<RemotePeer[]>([]);

  const upsertPeer = useCallback((connectionId: string, patch: Partial<RemotePeer>) => {
    setPeers((prev) => {
      const idx = prev.findIndex((p) => p.connectionId === connectionId);
      if (idx === -1) {
        return [...prev, {
          connectionId,
          sessionId: patch.sessionId ?? "",
          stream: patch.stream ?? new MediaStream(),
        }];
      }
      const next = [...prev];
      next[idx] = { ...next[idx], ...patch } as RemotePeer;
      return next;
    });
  }, []);

  const removePeer = useCallback((connectionId: string) => {
    const pc = pcsRef.current.get(connectionId);
    if (pc) {
      pc.close();
      pcsRef.current.delete(connectionId);
    }
    setPeers((prev) => prev.filter((p) => p.connectionId !== connectionId));
  }, []);

  const ensurePc = useCallback(
    (remote: PeerInfo): RTCPeerConnection => {
      let pc = pcsRef.current.get(remote.connectionId);
      if (pc) return pc;
      pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });

      if (localStream) {
        localStream.getTracks().forEach((t) => pc!.addTrack(t, localStream));
      }

      pc.ontrack = (ev) => {
        const [incoming] = ev.streams;
        if (incoming) {
          upsertPeer(remote.connectionId, { sessionId: remote.sessionId, stream: incoming });
        }
      };

      pc.onicecandidate = (ev) => {
        if (ev.candidate) {
          sendWebRtcSignal(remote.connectionId, "ICE_CANDIDATE", {
            candidate: ev.candidate.toJSON(),
          });
        }
      };

      pc.onconnectionstatechange = () => {
        if (pc && (pc.connectionState === "failed" || pc.connectionState === "closed")) {
          removePeer(remote.connectionId);
        }
      };

      pcsRef.current.set(remote.connectionId, pc);
      upsertPeer(remote.connectionId, { sessionId: remote.sessionId });
      return pc;
    },
    [localStream, sendWebRtcSignal, upsertPeer, removePeer],
  );

  const startOffer = useCallback(
    async (remote: PeerInfo) => {
      const pc = ensurePc(remote);
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      sendWebRtcSignal(remote.connectionId, "SDP_OFFER", { sdp: offer.sdp });
    },
    [ensurePc, sendWebRtcSignal],
  );

  const handleOffer = useCallback(
    async (from: PeerInfo, sdp: string) => {
      const pc = ensurePc(from);
      await pc.setRemoteDescription({ type: "offer", sdp });
      const answer = await pc.createAnswer();
      await pc.setLocalDescription(answer);
      sendWebRtcSignal(from.connectionId, "SDP_ANSWER", { sdp: answer.sdp });
    },
    [ensurePc, sendWebRtcSignal],
  );

  const handleAnswer = useCallback(async (from: PeerInfo, sdp: string) => {
    const pc = pcsRef.current.get(from.connectionId);
    if (!pc) return;
    await pc.setRemoteDescription({ type: "answer", sdp });
  }, []);

  const handleIce = useCallback(async (from: PeerInfo, candidate: RTCIceCandidateInit) => {
    const pc = pcsRef.current.get(from.connectionId);
    if (!pc) return;
    try {
      await pc.addIceCandidate(candidate);
    } catch {
      // candidate may arrive before remote description is set — browser will buffer
    }
  }, []);

  const handleSignal = useCallback(
    (event: "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE", payload: SdpIceFromRelay) => {
      const from: PeerInfo = { connectionId: payload.from, sessionId: payload.fromSessionId };
      if (event === "SDP_OFFER" && payload.sdp) return handleOffer(from, payload.sdp);
      if (event === "SDP_ANSWER" && payload.sdp) return handleAnswer(from, payload.sdp);
      if (event === "ICE_CANDIDATE" && payload.candidate) return handleIce(from, payload.candidate);
    },
    [handleOffer, handleAnswer, handleIce],
  );

  useEffect(() => {
    const pcs = pcsRef.current;
    return () => {
      pcs.forEach((pc) => pc.close());
      pcs.clear();
    };
  }, []);

  return { peers, startOffer, handleSignal, removePeer };
}
```

- [ ] **Step 2: Verify types**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd web
git add src/hooks/useWebRTC.ts
git commit -m "feat(web): add useWebRTC peer connection hook"
```

---

## Phase 4 — Web: Session Page Integration

### Task 4.1: Add `RemoteVideo` component

**Files:**
- Create: `web/src/components/session/RemoteVideo.tsx`

- [ ] **Step 1: Write it**

```tsx
import { useEffect, useRef } from "react";

export default function RemoteVideo({
  stream,
  displayName,
  muted = false,
  className = "",
}: {
  stream: MediaStream;
  displayName: string;
  muted?: boolean;
  className?: string;
}) {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    if (el.srcObject !== stream) el.srcObject = stream;
  }, [stream]);

  return (
    <div className={`relative rounded-xl overflow-hidden bg-black ${className}`}>
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted={muted}
        className="w-full h-full object-cover"
      />
      <div className="absolute bottom-2 left-2 text-xs font-medium text-white bg-black/50 px-2 py-1 rounded">
        {displayName}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd web
git add src/components/session/RemoteVideo.tsx
git commit -m "feat(web): add RemoteVideo component"
```

---

### Task 4.2: Refactor `VideoFeed` to accept an external `MediaStream` (stop managing its own)

**Files:**
- Modify: `web/src/components/session/VideoFeed.tsx`

**Why:** VideoFeed currently calls `getUserMedia` itself. With the new `useLocalMedia` hook we'd get two camera requests. This task hands ownership of the stream to the Session page.

- [ ] **Step 1: Replace the file contents**

Replace `web/src/components/session/VideoFeed.tsx` with:
```tsx
import { useRef, useEffect } from "react";

export default function VideoFeed({
  stream,
  showOverlay = true,
  isTracking = false,
}: {
  stream: MediaStream | null;
  showOverlay?: boolean;
  isTracking?: boolean;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    if (el.srcObject !== stream) el.srcObject = stream;
  }, [stream]);

  return (
    <div className="relative w-full rounded-2xl overflow-hidden border border-nimbus-mist/10 bg-nimbus-elevated">
      <div className="relative w-full" style={{ paddingBottom: "56.25%" }}>
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className="absolute inset-0 w-full h-full object-cover"
          style={{ transform: "scaleX(-1)" }}
        />

        {showOverlay && (
          <canvas
            className="absolute inset-0 w-full h-full pointer-events-none"
            aria-hidden="true"
          />
        )}

        <div className="absolute top-3 left-3">
          <div
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium backdrop-blur-sm ${
              isTracking
                ? "bg-nimbus-teal/20 text-nimbus-teal border border-nimbus-teal/30"
                : "bg-nimbus-surface/60 text-nimbus-mist border border-nimbus-mist/20"
            }`}
          >
            <span className={`w-1.5 h-1.5 rounded-full ${isTracking ? "bg-nimbus-teal signal-pulse" : "bg-nimbus-mist"}`} />
            {isTracking ? "Tracking" : "Waiting…"}
          </div>
        </div>

        {showOverlay && (
          <div className="absolute top-3 right-3">
            <button
              className="p-1.5 rounded-lg bg-nimbus-surface/60 text-nimbus-mist hover:text-nimbus-text backdrop-blur-sm border border-nimbus-mist/20 transition-colors"
              title="Toggle skeleton overlay"
              aria-label="Toggle MediaPipe skeleton overlay"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                <circle cx="12" cy="12" r="3" />
              </svg>
            </button>
          </div>
        )}

        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background: "radial-gradient(ellipse at center, transparent 60%, rgba(15, 22, 41, 0.4) 100%)",
          }}
          aria-hidden="true"
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify TypeScript**

Run: `cd web && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd web
git add src/components/session/VideoFeed.tsx
git commit -m "feat(web): VideoFeed accepts external stream prop"
```

---

### Task 4.3: Rewire the `Session` page with real hooks

**Files:**
- Modify: `web/src/pages/Session.tsx`

- [ ] **Step 1: Replace the demo data wiring**

Replace the contents of `web/src/pages/Session.tsx` with:
```tsx
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useAuth } from "../context/AuthContext.tsx";
import { useLocalMedia } from "../hooks/useLocalMedia.ts";
import { useSessionSocket, type InboundSignal, type PeerInfo } from "../hooks/useSessionSocket.ts";
import { useWebRTC } from "../hooks/useWebRTC.ts";
import VideoFeed from "../components/session/VideoFeed.tsx";
import RemoteVideo from "../components/session/RemoteVideo.tsx";
import GlossTicker from "../components/session/GlossTicker.tsx";
import CaptionBar from "../components/session/CaptionBar.tsx";
import ParticipantsPanel from "../components/session/ParticipantsPanel.tsx";
import StatusOrb from "../components/ui/StatusOrb.tsx";
import NimbusButton from "../components/ui/NimbusButton.tsx";

export default function Session() {
  const { roomId } = useParams<{ roomId: string }>();
  const { user, idToken } = useAuth();
  const [panelOpen, setPanelOpen] = useState(true);

  // Stable sessionId for the lifetime of this page render
  const sessionId = useMemo(() => crypto.randomUUID(), []);

  const { stream: localStream, error: mediaError } = useLocalMedia(true);

  // We have to forward-declare the signal-handler because the hooks depend on each other.
  const [incoming, setIncoming] = useState<InboundSignal | null>(null);
  const onMessage = (msg: InboundSignal) => setIncoming(msg);

  const { status, sendWebRtcSignal } = useSessionSocket({
    token: idToken,
    sessionId,
    roomId: roomId ?? null,
    onMessage,
  });

  const { peers, startOffer, handleSignal, removePeer } = useWebRTC({
    localStream,
    sendWebRtcSignal,
  });

  // React to inbound signals
  useEffect(() => {
    if (!incoming) return;
    if (incoming.type !== "SIGNAL") return;
    if (incoming.event === "JOIN_ROOM") {
      // Existing peers will send offers OR we initiate to each.
      // Convention: the *newly-joined* peer (us) initiates to all existing peers.
      incoming.payload.peers.forEach((p: PeerInfo) => startOffer(p));
    } else if (incoming.event === "PEER_JOINED") {
      // Existing peer pattern — we wait, they'll send the offer.
      // Nothing to do until SDP_OFFER arrives.
    } else if (incoming.event === "PEER_LEFT") {
      removePeer(incoming.payload.connectionId);
    } else if (
      incoming.event === "SDP_OFFER" ||
      incoming.event === "SDP_ANSWER" ||
      incoming.event === "ICE_CANDIDATE"
    ) {
      handleSignal(incoming.event, incoming.payload);
    }
  }, [incoming, startOffer, handleSignal, removePeer]);

  const orbState: "active" | "warming" | "error" | "idle" =
    status === "open" ? "active" : status === "error" ? "error" : "idle";

  return (
    <div className="h-[calc(100vh-52px)] flex flex-col bg-nimbus-bg">
      <div className="flex items-center justify-between px-4 py-2 border-b border-nimbus-mist/10 bg-white/60 backdrop-blur-sm">
        <div className="flex items-center gap-4">
          <span className="text-xs font-mono text-nimbus-mist">
            Room: <span className="text-nimbus-text font-medium">{roomId}</span>
          </span>
          <span className="text-xs text-nimbus-mist">
            Signed in as <span className="text-nimbus-text">{user?.displayName ?? "…"}</span>
          </span>
        </div>
        <div className="flex items-center gap-4">
          <StatusOrb state={orbState} />
          <button
            onClick={() => setPanelOpen(!panelOpen)}
            className="p-2 rounded-lg hover:bg-nimbus-surface text-nimbus-mist hover:text-nimbus-text"
            title="Toggle participants"
          >
            Participants
          </button>
          <NimbusButton variant="danger" size="sm" onClick={() => window.history.back()}>
            End Session
          </NimbusButton>
        </div>
      </div>

      <div className="flex-1 flex gap-4 p-4 overflow-hidden">
        <div className="flex-1 flex flex-col gap-3 min-w-0">
          <div className="flex-shrink-0">
            <VideoFeed stream={localStream} showOverlay isTracking={!!localStream} />
            {mediaError && (
              <div className="mt-2 text-sm text-red-600">
                Camera/mic error: {mediaError}
              </div>
            )}
          </div>

          <GlossTicker tokens={[]} />

          <div className="flex-1 min-h-0">
            <CaptionBar captions={[]} />
          </div>
        </div>

        <div className="w-72 flex flex-col gap-3">
          <ParticipantsPanel
            roomId={roomId || "unknown"}
            participants={[
              { id: sessionId, displayName: user?.displayName ?? "You", isSigning: false },
              ...peers.map((p) => ({
                id: p.sessionId,
                displayName: "Peer",
                isSigning: false,
              })),
            ]}
            emotion="CALM"
            emotionConfidence={0}
            open={panelOpen}
            onToggle={() => setPanelOpen(false)}
          />
          <div className="flex flex-col gap-2">
            {peers.map((p) => (
              <RemoteVideo
                key={p.connectionId}
                stream={p.stream}
                displayName="Peer"
                className="aspect-video w-full"
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Run typecheck**

Run: `cd web && npx tsc --noEmit`
Expected: any errors (e.g., if `VideoFeed`'s `stream` prop signature wasn't added) must be fixed inline before moving on.

- [ ] **Step 3: Commit**

```bash
cd web
git add src/pages/Session.tsx
git commit -m "feat(web): Session page uses WebSocket + WebRTC hooks"
```

---

## Phase 5 — End-to-End Verification

### Task 5.1: Single-machine two-tab test

**Files:** none

- [ ] **Step 1: Set `.env.local`**

```bash
cd web
cp .env.example .env.local
# Fill in VITE_COGNITO_USER_POOL_ID, VITE_COGNITO_CLIENT_ID, VITE_NIMBUS_WS_URL
```

- [ ] **Step 2: Start dev server**

Run: `cd web && npm run dev`

- [ ] **Step 3: Open two browser tabs, both signed into the app**

- Tab A: navigate to `/session/test-room-1`
- Tab B (different browser profile OR incognito with a second Cognito user): navigate to `/session/test-room-1`

- [ ] **Step 4: Verify**

Expected:
1. Both tabs show their own webcam in `VideoFeed`.
2. Each tab lists one remote participant in `ParticipantsPanel`.
3. Remote video tiles show the other tab's webcam feed, with audio (one tab should have mic muted to avoid feedback).
4. Closing tab A → tab B shows the peer being removed within ~5 seconds.

- [ ] **Step 5: Collect diagnostics if it fails**

Check browser DevTools → Network → WS frames for the signaling exchange:
- Both tabs should send `JOIN_ROOM`, receive ack.
- One tab should send `WEBRTC_SIGNAL` with `SDP_OFFER`, other should relay back `SDP_ANSWER`.
- ICE candidates both directions.

Also check CloudWatch log group `/aws/lambda/NIMBUS_PROD_WebRtcSignal` for relay errors.

- [ ] **Step 6: Commit (nothing to commit if pass) — move to Task 5.2**

---

### Task 5.2: Two-device test

**Files:** none

- [ ] **Step 1: Expose the web dev server**

Option A (same LAN): `npm run dev -- --host 0.0.0.0` and browse from device 2 to `http://<laptop-lan-ip>:5173`.
Note: `getUserMedia` requires either HTTPS or `localhost`, so the second device must use the laptop's mDNS name if possible or use the hosted build (next option).

Option B (preferred): `npm run build && npm run preview -- --host 0.0.0.0`, then use a temporary HTTPS tunnel:
```bash
# in another terminal
npx ngrok http 4173
```
Use the `https://...ngrok.app` URL from both devices.

- [ ] **Step 2: Both devices sign in (different Cognito users) and navigate to same roomId**

- [ ] **Step 3: Verify both see each other's video**

If it fails between devices despite working locally: likely NAT traversal. Document the limitation and note that deploying a TURN server (or using `twilio-network-traversal` for quick validation) would resolve. This is outside the MVP scope.

---

## Phase 6 — Cleanup & Handoff

### Task 6.1: Update README with the new env var + flow

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add a Web section**

Append after the existing "Getting Started" section:
```markdown
4. **Web Frontend**:
   - `cd web/`
   - `cp .env.example .env.local` and fill in Cognito IDs + `VITE_NIMBUS_WS_URL` from `sam deploy` outputs.
   - `npm install && npm run dev`
   - Open two browser profiles at `http://localhost:5173/session/<same-room-id>` to test a peer-to-peer video call.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: document web frontend setup + peer video call flow"
```

---

### Task 6.2: Open the PR

**Files:** none

- [ ] **Step 1: Push the branch**

```bash
git push -u origin infrastructure-and-signaling
```

- [ ] **Step 2: Create the PR**

```bash
gh pr create --title "feat: integrate web frontend with AWS WS for 2-peer video calls" --body "$(cat <<'EOF'
## Summary
- Adds `WEBRTC_SIGNAL` route + Lambda relay for SDP/ICE
- Extends JOIN_ROOM to return existing peers and broadcast PEER_JOINED
- Adds PEER_LEFT broadcast on leave / disconnect
- Wires React Session page to AWS WebSocket + native RTCPeerConnection
- Supports 2-peer video calls; >2 peers unchanged (mediasoup path preserved for future)

## Test plan
- [ ] Backend unit tests pass: `cd backend && python -m pytest tests/`
- [ ] SAM template validates: `sam validate --lint`
- [ ] Two browser tabs in same room see each other's video
- [ ] Two devices (same LAN or ngrok) see each other's video
- [ ] Closing one tab → peer is removed from the other within 5s
EOF
)"
```

---

## Appendix — Protocol Message Reference (added by this plan)

**Client → Server**

```jsonc
// Join a room — ACK includes existing peers
{ "action": "JOIN_ROOM", "sessionId": "<uuid>", "roomId": "<id>" }

// Relay WebRTC negotiation to one peer in the same room
{
  "action":    "WEBRTC_SIGNAL",
  "sessionId": "<uuid>",
  "roomId":    "<id>",
  "target":    "<connectionId>",
  "signal":    "SDP_OFFER" | "SDP_ANSWER" | "ICE_CANDIDATE",
  "payload":   { "sdp": "..." } | { "candidate": {...} }
}
```

**Server → Client (all wrapped as `{type: "SIGNAL", event, sessionId, roomId, payload}`):**
- `JOIN_ROOM` → `payload.peers: [{connectionId, sessionId}, ...]`
- `PEER_JOINED` → `payload: {connectionId, sessionId}`
- `PEER_LEFT` → `payload: {connectionId, sessionId}`
- `SDP_OFFER` / `SDP_ANSWER` → `payload: {sdp, from, fromSessionId}`
- `ICE_CANDIDATE` → `payload: {candidate, from, fromSessionId}`

---

## Mediasoup Future Path (not in MVP)

The mediasoup SFU (`infrastructure/mediasoup/`) is already fully implemented as a Node service but not deployed. For >2 peers in the future:

1. Deploy EC2 with `DeployMediasoupEnabled=true` params in `sam deploy`.
2. Provision TLS cert at `/etc/nimbus/tls/fullchain.pem` (ACM export or LetsEncrypt).
3. Set `MediasoupAnnouncedIp` after EIP allocation.
4. Install `mediasoup-client` in `web/`; add a `useMediasoup.ts` hook analogous to `useWebRTC.ts` but consuming the SFU RPCs.
5. Switch `Session.tsx` over (or feature-flag between P2P and SFU paths).

This phase stays out of scope here because (a) TLS provisioning is a blocker for hackathon speed, (b) 2-peer video calls work fine with P2P + public STUN, and (c) the mediasoup codebase already has unit tests keeping it green.
