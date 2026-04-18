"""End-to-end smoke tests against the deployed API Gateway WebSocket.

These exercise the connect → join → broadcast → leave → disconnect flow using
the real AWS services. They require a deployed stack; see conftest.py for the
env vars that gate them.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

import boto3
import pytest
import websockets


async def _recv_json(ws, timeout: float = 5.0) -> dict[str, Any]:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def _connect(websocket_url: str, session_id: str, room_id: str):
    url = f"{websocket_url}?sessionId={session_id}&roomId={room_id}"
    return await websockets.connect(url, open_timeout=10)


@pytest.mark.asyncio
async def test_connect_rejects_non_uuid_session(websocket_url):
    url = f"{websocket_url}?sessionId=not-a-uuid&roomId=test"
    # API Gateway returns a 403-equivalent by closing the handshake.
    with pytest.raises(
        (
            websockets.exceptions.InvalidStatus,
            websockets.exceptions.InvalidStatusCode,
            websockets.exceptions.ConnectionClosedError,
        )
    ):
        async with await websockets.connect(url, open_timeout=10):
            pass


@pytest.mark.asyncio
async def test_connect_accepts_valid_uuid(websocket_url):
    sid = str(uuid.uuid4())
    async with await _connect(websocket_url, sid, "smoke-test") as ws:
        # No message is pushed on connect; just verifying the socket is open.
        assert ws.open is True or ws.open is None  # version-dependent attr


@pytest.mark.asyncio
async def test_join_and_leave_room_emit_acks(websocket_url):
    sid = str(uuid.uuid4())
    room_id = f"smoke-{uuid.uuid4().hex[:8]}"
    async with await _connect(websocket_url, sid, room_id) as ws:
        await ws.send(
            json.dumps({"action": "JOIN_ROOM", "sessionId": sid, "roomId": room_id})
        )
        join_ack = await _recv_json(ws)
        assert join_ack["type"] == "SIGNAL"
        assert join_ack["event"] == "JOIN_ROOM"
        assert join_ack["roomId"] == room_id
        assert join_ack["payload"]["status"] == "joined"

        await ws.send(
            json.dumps({"action": "LEAVE_ROOM", "sessionId": sid, "roomId": room_id})
        )
        leave_ack = await _recv_json(ws)
        assert leave_ack["event"] == "LEAVE_ROOM"
        assert leave_ack["payload"]["status"] == "left"


@pytest.mark.asyncio
async def test_join_room_persists_to_dynamodb(
    websocket_url, rooms_table_name, aws_region
):
    sid = str(uuid.uuid4())
    room_id = f"smoke-{uuid.uuid4().hex[:8]}"
    ddb = boto3.resource("dynamodb", region_name=aws_region)
    rooms = ddb.Table(rooms_table_name)

    async with await _connect(websocket_url, sid, room_id) as ws:
        await ws.send(
            json.dumps({"action": "JOIN_ROOM", "sessionId": sid, "roomId": room_id})
        )
        await _recv_json(ws)  # consume ack

        # Give DDB a beat to settle (writes are strongly consistent but Lambda
        # may return ack before put_item completes on slow cold starts).
        await asyncio.sleep(0.5)

        resp = rooms.query(
            KeyConditionExpression="roomId = :r",
            ExpressionAttributeValues={":r": room_id},
        )
        items = resp.get("Items", [])
        assert len(items) == 1
        assert items[0]["sessionId"] == sid

    # After the socket closes, ws_disconnect should sweep the row.
    await asyncio.sleep(1.0)
    resp = rooms.query(
        KeyConditionExpression="roomId = :r",
        ExpressionAttributeValues={":r": room_id},
    )
    assert resp.get("Items", []) == []


@pytest.mark.asyncio
async def test_broadcast_caption_fans_out_to_all_participants(
    websocket_url, broadcast_function_name, aws_region
):
    room_id = f"smoke-{uuid.uuid4().hex[:8]}"
    sid_a = str(uuid.uuid4())
    sid_b = str(uuid.uuid4())

    async with await _connect(websocket_url, sid_a, room_id) as ws_a, \
            await _connect(websocket_url, sid_b, room_id) as ws_b:
        for ws, sid in ((ws_a, sid_a), (ws_b, sid_b)):
            await ws.send(
                json.dumps(
                    {"action": "JOIN_ROOM", "sessionId": sid, "roomId": room_id}
                )
            )
            await _recv_json(ws)  # join ack

        # Directly invoke the BroadcastCaption Lambda the way ProcessFrame
        # (Member 2) eventually will.
        lam = boto3.client("lambda", region_name=aws_region)
        payload = {
            "roomId": room_id,
            "caption": {
                "type": "CAPTION",
                "sessionId": sid_a,
                "timestamp": "2026-04-18T00:00:00Z",
                "sequenceNumber": 1,
                "payload": {"text": "integration-test-caption"},
            },
        }
        result = lam.invoke(
            FunctionName=broadcast_function_name,
            Payload=json.dumps(payload).encode("utf-8"),
        )
        body = json.loads(result["Payload"].read())
        assert body["ok"] is True
        assert body["delivered"] == 2

        # Both peers should see the CAPTION message.
        msg_a = await _recv_json(ws_a)
        msg_b = await _recv_json(ws_b)
        assert msg_a["type"] == "CAPTION"
        assert msg_b["type"] == "CAPTION"
        assert msg_a["payload"]["text"] == "integration-test-caption"
        assert msg_b["payload"]["text"] == "integration-test-caption"
