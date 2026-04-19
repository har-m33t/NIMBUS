"""Helpers for ``NIMBUS_PROD_Sessions`` (PROTOCOLS.md §2.1).

Schema:
    PK  sessionId (S)
    SK  sk (S)

Normal session state lives on ``sk="STATE"`` so the signaling Lambdas and the
AI pipeline share one item per session. Special rows reuse the same table:
    - ``sessionId="CONN#<connectionId>", sk="INDEX"`` for reverse lookups
    - ``sessionId="bedrock_global", sk="RATE_LIMIT"`` for the Bedrock token bucket
"""

from __future__ import annotations

import os
import time
from decimal import Decimal
from typing import Any

import boto3

TABLE_NAME = os.environ.get("SESSIONS_TABLE", "NIMBUS_PROD_Sessions")
TTL_SECONDS = 4 * 60 * 60  # 4 hours per PROTOCOLS.md §2.1
STATE_SORT_KEY = "STATE"

_ddb = None


def _table():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _ddb


def _now_ms() -> int:
    return int(time.time() * 1000)


def _pipeline_key(session_id: str, sort_key: str = STATE_SORT_KEY) -> dict[str, str]:
    return {"sessionId": session_id, "sk": sort_key}


def append_gloss(
    session_id: str,
    tokens: list[str],
    connection_id: str,
    room_id: str,
    domain_name: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """Append tokens to the shared session STATE item."""
    now_ms = _now_ms()
    update_parts = [
        "lastTokenAt = :now",
        "firstTokenAt = if_not_exists(firstTokenAt, :now)",
        "connectionId = :cid",
        "roomId = :rid",
        "lastEmotion = :emo",
        "#ttl = :ttl",
        "glossBuffer = list_append(if_not_exists(glossBuffer, :empty), :tok)",
    ]
    values: dict[str, Any] = {
        ":now": Decimal(now_ms),
        ":cid": connection_id,
        ":rid": room_id,
        ":emo": "CALM",
        ":ttl": Decimal(int(time.time()) + TTL_SECONDS),
        ":empty": [],
        ":tok": tokens,
    }
    names = {"#ttl": "ttl"}
    if domain_name:
        update_parts.append("domainName = :domain")
        values[":domain"] = domain_name
    if stage:
        update_parts.append("#stage = :stage")
        names["#stage"] = "stage"
        values[":stage"] = stage

    resp = _table().update_item(
        Key=_pipeline_key(session_id),
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    attrs = resp["Attributes"]
    attrs.setdefault("sk", STATE_SORT_KEY)
    return attrs


def drain_buffer(session_id: str, sort_key: str = STATE_SORT_KEY) -> list[str] | None:
    """Atomically remove glossBuffer and stamp lastCaptionAt."""
    try:
        resp = _table().update_item(
            Key=_pipeline_key(session_id, sort_key or STATE_SORT_KEY),
            UpdateExpression="REMOVE glossBuffer, firstTokenAt SET lastCaptionAt = :now",
            ConditionExpression="attribute_exists(glossBuffer) AND size(glossBuffer) > :zero",
            ExpressionAttributeValues={":now": Decimal(_now_ms()), ":zero": 0},
            ReturnValues="ALL_OLD",
        )
        return list(resp["Attributes"].get("glossBuffer", []))
    except _table().meta.client.exceptions.ConditionalCheckFailedException:
        return None


def get_session(session_id: str, sort_key: str = STATE_SORT_KEY) -> dict | None:
    """Fetch a single session item. Returns None if not found."""
    resp = _table().get_item(Key=_pipeline_key(session_id, sort_key or STATE_SORT_KEY))
    return resp.get("Item")


def recent_captions(session_id: str, limit: int = 3) -> list[str]:
    """Fetch last N captions for Bedrock prompt context (PROTOCOLS.md §2.3)."""
    item = get_session(session_id) or {}
    recent = item.get("recentCaptions") or []
    if isinstance(recent, list):
        return [str(text) for text in recent[-limit:] if text]
    caption = item.get("captionText")
    return [str(caption)] if caption else []


def record_caption(session_id: str, text: str, sort_key: str = STATE_SORT_KEY) -> None:
    """Persist caption history on the shared STATE item."""
    if not text:
        return
    _table().update_item(
        Key=_pipeline_key(session_id, sort_key or STATE_SORT_KEY),
        UpdateExpression=(
            "SET captionText = :text, "
            "lastCaptionAt = :now, "
            "#ttl = :ttl, "
            "recentCaptions = list_append(if_not_exists(recentCaptions, :empty), :caption)"
        ),
        ExpressionAttributeNames={"#ttl": "ttl"},
        ExpressionAttributeValues={
            ":text": text,
            ":now": Decimal(_now_ms()),
            ":ttl": Decimal(int(time.time()) + TTL_SECONDS),
            ":empty": [],
            ":caption": [text],
        },
    )
