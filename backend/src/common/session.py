"""Helpers for ``NIMBUS_PROD_Sessions`` (PROTOCOLS.md §2.1).

Schema:
    PK  sessionId (S)
    SK  timestamp (S, ISO-8601)
    glossBuffer    list<string>
    firstTokenAt   number (epoch ms)
    lastTokenAt    number (epoch ms)
    lastEmotion    string           -- always "CALM" per C1
    lastCaptionAt  number (epoch ms)
    connectionId   string
    ttl            number (epoch s, now + 4h)
"""

from __future__ import annotations

import os
import time
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

TABLE_NAME = os.environ.get("SESSIONS_TABLE", "NIMBUS_PROD_Sessions")
TTL_SECONDS = 4 * 60 * 60  # 4 hours per PROTOCOLS.md §2.1

_ddb = None


def _table():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _ddb


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())


def append_gloss(session_id: str, tokens: list[str], connection_id: str, room_id: str) -> dict:
    """Append tokens, stamp firstTokenAt if new, always update lastTokenAt."""
    now_ms = _now_ms()
    resp = _table().update_item(
        Key={"sessionId": session_id, "timestamp": _iso_now()},
        UpdateExpression=(
            "SET lastTokenAt = :now, "
            "firstTokenAt = if_not_exists(firstTokenAt, :now), "
            "connectionId = :cid, roomId = :rid, lastEmotion = :emo, "
            "#ttl = :ttl, "
            "glossBuffer = list_append(if_not_exists(glossBuffer, :empty), :tok)"
        ),
        ExpressionAttributeNames={"#ttl": "ttl"},
        ExpressionAttributeValues={
            ":now": Decimal(now_ms),
            ":cid": connection_id,
            ":rid": room_id,
            ":emo": "CALM",
            ":ttl": Decimal(int(time.time()) + TTL_SECONDS),
            ":empty": [],
            ":tok": tokens,
        },
        ReturnValues="ALL_NEW",
    )
    return resp["Attributes"]


def drain_buffer(session_id: str, sort_key: str) -> list[str] | None:
    """Atomically remove glossBuffer and stamp lastCaptionAt. Returns tokens or None if already drained."""
    try:
        resp = _table().update_item(
            Key={"sessionId": session_id, "timestamp": sort_key},
            UpdateExpression="REMOVE glossBuffer, firstTokenAt SET lastCaptionAt = :now",
            ConditionExpression="attribute_exists(glossBuffer) AND size(glossBuffer) > :zero",
            ExpressionAttributeValues={":now": Decimal(_now_ms()), ":zero": 0},
            ReturnValues="ALL_OLD",
        )
        return list(resp["Attributes"].get("glossBuffer", []))
    except _table().meta.client.exceptions.ConditionalCheckFailedException:
        return None


def get_session(session_id: str, sort_key: str) -> dict | None:
    """Fetch a single session item. Returns None if not found."""
    resp = _table().get_item(Key={"sessionId": session_id, "timestamp": sort_key})
    return resp.get("Item")


def recent_captions(session_id: str, limit: int = 3) -> list[str]:
    """Fetch last N captions for Bedrock prompt context (PROTOCOLS.md §2.3)."""
    resp = _table().query(
        KeyConditionExpression=Key("sessionId").eq(session_id),
        FilterExpression="attribute_exists(captionText)",
        ScanIndexForward=False,
        Limit=limit,
    )
    return [item["captionText"] for item in resp.get("Items", [])]
