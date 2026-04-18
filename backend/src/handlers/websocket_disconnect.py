"""NIMBUS_PROD_WS_Disconnect — WebSocket $disconnect route."""

from __future__ import annotations

import os
from typing import Any

import boto3

SESSIONS_TABLE = os.environ.get("SESSIONS_TABLE", "NIMBUS_PROD_Sessions")

_ddb = None


def _table():
    global _ddb
    if _ddb is None:
        _ddb = boto3.resource("dynamodb").Table(SESSIONS_TABLE)
    return _ddb


def handler(event: dict, _context: Any) -> dict:
    conn_id = event.get("requestContext", {}).get("connectionId", "")
    if conn_id:
        try:
            _table().delete_item(Key={"sessionId": conn_id, "timestamp": "CONNECTION"})
        except Exception:
            pass
    return {"statusCode": 200}
