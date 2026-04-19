"""Helpers for ``NIMBUS_PROD_Sessions`` (PROTOCOLS.md §2.1).

Schema (aligned with Member 1's template.yaml KeySchema):
    PK  sessionId (S)
    SK  sk (S)         — "STATE" for live record, "CAPTION#<ISO>" for history,
                         "RATE#bedrock" for rate-limit bucket
    glossBuffer    list<string>
    firstTokenAt   number (epoch ms)
    lastTokenAt    number (epoch ms)
    lastEmotion    string           -- "CALM" until Rekognition is enabled
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

STATE_SK = "STATE"

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


def append_gloss(
    session_id: str,
    tokens: list[str],
    connection_id: str,
    room_id: str,
    emotion: str = "CALM",
) -> dict:
    """Append tokens to the STATE record, stamp firstTokenAt if new.

    emotion is written with if_not_exists so it is initialised on first call
    but never overwritten between Rekognition detections — update_emotion()
    is the authoritative writer.
    """
    now_ms = _now_ms()
    resp = _table().update_item(
        Key={"sessionId": session_id, "sk": STATE_SK},
        UpdateExpression=(
            "SET lastTokenAt = :now, "
            "firstTokenAt = if_not_exists(firstTokenAt, :now), "
            "connectionId = :cid, roomId = :rid, "
            "lastEmotion = if_not_exists(lastEmotion, :emo), "
            "#ttl = :ttl, "
            "glossBuffer = list_append(if_not_exists(glossBuffer, :empty), :tok)"
        ),
        ExpressionAttributeNames={"#ttl": "ttl"},
        ExpressionAttributeValues={
            ":now": Decimal(now_ms),
            ":cid": connection_id,
            ":rid": room_id,
            ":emo": emotion,
            ":ttl": Decimal(int(time.time()) + TTL_SECONDS),
            ":empty": [],
            ":tok": tokens,
        },
        ReturnValues="ALL_NEW",
    )
    return resp["Attributes"]


def update_emotion(session_id: str, emotion: str) -> None:
    """Overwrite lastEmotion on the STATE record after a Rekognition detection."""
    _table().update_item(
        Key={"sessionId": session_id, "sk": STATE_SK},
        UpdateExpression="SET lastEmotion = :emo",
        ExpressionAttributeValues={":emo": emotion},
    )


def drain_buffer(session_id: str, sort_key: str = STATE_SK) -> list[str] | None:
    """Atomically remove glossBuffer from the STATE record.

    Returns the drained tokens or None if already drained (concurrent flush).
    The sort_key param is kept for backwards compat with tests; production
    callers should omit it (defaults to STATE_SK).
    """
    try:
        resp = _table().update_item(
            Key={"sessionId": session_id, "sk": sort_key},
            UpdateExpression="REMOVE glossBuffer, firstTokenAt SET lastCaptionAt = :now",
            ConditionExpression="attribute_exists(glossBuffer) AND size(glossBuffer) > :zero",
            ExpressionAttributeValues={":now": Decimal(_now_ms()), ":zero": 0},
            ReturnValues="ALL_OLD",
        )
        return list(resp["Attributes"].get("glossBuffer", []))
    except _table().meta.client.exceptions.ConditionalCheckFailedException:
        return None


def get_session(session_id: str, sort_key: str = STATE_SK) -> dict | None:
    """Fetch a single session item. Returns None if not found."""
    resp = _table().get_item(Key={"sessionId": session_id, "sk": sort_key})
    return resp.get("Item")


def store_caption(session_id: str, text: str) -> None:
    """Write a CAPTION history item for Bedrock context (PROTOCOLS.md §2.3)."""
    _table().put_item(Item={
        "sessionId": session_id,
        "sk": f"CAPTION#{_iso_now()}",
        "captionText": text,
        "ttl": int(time.time()) + TTL_SECONDS,
    })


def recent_captions(session_id: str, limit: int = 3) -> list[str]:
    """Fetch last N captions for Bedrock prompt context (PROTOCOLS.md §2.3)."""
    resp = _table().query(
        KeyConditionExpression=(
            Key("sessionId").eq(session_id) & Key("sk").begins_with("CAPTION#")
        ),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [item["captionText"] for item in resp.get("Items", [])]
