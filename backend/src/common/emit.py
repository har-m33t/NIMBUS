"""Post events back to the originating WebSocket connection.

Room-level fan-out (CAPTION → all participants) is Member 1's
``NIMBUS_PROD_BroadcastCaption``. This module only talks to the single
connectionId that sent the current INFER.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

from .logger import logger

_client = None


def _mgmt_client(event: dict):
    """Build (or reuse) an apigatewaymanagementapi client from the event."""
    global _client
    if _client is not None:
        return _client
    endpoint = os.environ.get("APIGW_MANAGEMENT_ENDPOINT")
    if not endpoint:
        ctx = event.get("requestContext", {})
        domain = ctx.get("domainName")
        stage = ctx.get("stage")
        endpoint = f"https://{domain}/{stage}"
    _client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)
    return _client


def post_to_connection(event: dict, connection_id: str, payload: dict[str, Any]) -> bool:
    """Return True on success, False on GoneException (stale connection)."""
    client = _mgmt_client(event)
    try:
        client.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(payload).encode("utf-8"),
        )
        return True
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("GoneException", "410"):
            logger.warning("connection gone", extra={"connectionId": connection_id})
            return False
        raise
