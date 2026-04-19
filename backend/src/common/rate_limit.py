"""DynamoDB-backed global token bucket for Bedrock calls.

Hackathon policy C3: strictly < 1 RPS across the whole stack. The bucket
lives on a single item on ``NIMBUS_PROD_Sessions`` keyed by
``sessionId="bedrock_global", sk="RATE_LIMIT"`` so we do not stand up
another table.

Algorithm: lazy refill - on each attempt, compute
``tokens = min(capacity, tokens + elapsed_s * refill_rate)`` and then
atomically require ``tokens >= 1`` while subtracting 1.
"""

from __future__ import annotations

import os
import time
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from .errors import RateLimitExceeded

TABLE_NAME = os.environ.get("SESSIONS_TABLE", "NIMBUS_PROD_Sessions")
BUCKET_PK = os.environ.get("RATE_LIMIT_PK", "bedrock_global")
SORT_KEY = "RATE_LIMIT"
CAPACITY = 1.0
REFILL_PER_SEC = 1.0  # < 1 RPS ceiling

_table = None


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _table


def _now_ms() -> int:
    return int(time.time() * 1000)


def try_acquire() -> bool:
    """Attempt to take one token. Returns True on success, False if empty."""
    t = _get_table()
    now_ms = _now_ms()
    resp = t.get_item(Key={"sessionId": BUCKET_PK, "sk": SORT_KEY})
    item = resp.get("Item")
    if item is None:
        try:
            t.put_item(
                Item={
                    "sessionId": BUCKET_PK,
                    "sk": SORT_KEY,
                    "tokens": Decimal("0"),  # start empty -> forces 1s warmup
                    "lastRefillMs": Decimal(now_ms),
                },
                ConditionExpression="attribute_not_exists(sessionId)",
            )
        except ClientError:
            pass
        return False

    last_ms = int(item["lastRefillMs"])
    tokens = float(item["tokens"])
    elapsed_s = max(0.0, (now_ms - last_ms) / 1000.0)
    refilled = min(CAPACITY, tokens + elapsed_s * REFILL_PER_SEC)
    if refilled < 1.0:
        try:
            t.update_item(
                Key={"sessionId": BUCKET_PK, "sk": SORT_KEY},
                UpdateExpression="SET tokens = :t, lastRefillMs = :n",
                ConditionExpression="lastRefillMs = :prev",
                ExpressionAttributeValues={
                    ":t": Decimal(str(refilled)),
                    ":n": Decimal(now_ms),
                    ":prev": Decimal(last_ms),
                },
            )
        except ClientError:
            pass
        return False

    try:
        t.update_item(
            Key={"sessionId": BUCKET_PK, "sk": SORT_KEY},
            UpdateExpression="SET tokens = :t, lastRefillMs = :n",
            ConditionExpression="lastRefillMs = :prev",
            ExpressionAttributeValues={
                ":t": Decimal(str(refilled - 1.0)),
                ":n": Decimal(now_ms),
                ":prev": Decimal(last_ms),
            },
        )
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def acquire_or_raise(timeout_ms: int = 2000, poll_ms: int = 100) -> None:
    """Spin-wait up to timeout_ms for a token. Raises RateLimitExceeded on timeout."""
    deadline = _now_ms() + timeout_ms
    while _now_ms() < deadline:
        if try_acquire():
            return
        time.sleep(poll_ms / 1000.0)
    raise RateLimitExceeded("Bedrock global 1 RPS budget exhausted")
