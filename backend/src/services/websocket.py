"""API Gateway Management API helpers used for fan-out.

PROTOCOLS.md §7: caption broadcast uses PostToConnection to deliver payloads
to every connectionId currently joined to a given roomId.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Iterable

import boto3
from botocore.exceptions import ClientError

_log = logging.getLogger(__name__)

_WS_ENDPOINT = os.environ.get("WEBSOCKET_ENDPOINT", "")


def _client(endpoint: str | None = None):
    endpoint = endpoint or _WS_ENDPOINT
    if not endpoint:
        raise RuntimeError("WEBSOCKET_ENDPOINT is not configured")
    return boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)


def post_to_connection(connection_id: str, payload: dict) -> bool:
    """Send one payload. Returns False if the connection is gone."""
    payload_preview = json.dumps(payload)[:200]
    _log.info("post_to_connection target=%s payload_preview=%s", connection_id, payload_preview)
    try:
        _client().post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps(payload).encode("utf-8"),
        )
        _log.info("post_to_connection delivered target=%s", connection_id)
        return True
    except ClientError as err:
        code = err.response.get("Error", {}).get("Code")
        if code == "GoneException":
            _log.info(
                "post_to_connection GoneException target=%s — connection is stale, payload_preview=%s",
                connection_id, payload_preview,
            )
            return False
        _log.exception("PostToConnection failed for %s", connection_id)
        raise


def broadcast(connection_ids: Iterable[str], payload: dict) -> list[str]:
    """Send payload to every connection. Returns the list of stale connectionIds."""
    targets = list(connection_ids)
    _log.info("broadcast total_targets=%d payload_preview=%s", len(targets), json.dumps(payload)[:200])
    stale: list[str] = []
    succeeded: list[str] = []
    for cid in targets:
        if not post_to_connection(cid, payload):
            stale.append(cid)
        else:
            succeeded.append(cid)
    _log.info(
        "broadcast complete total=%d succeeded=%d stale=%d succeeded_ids=%s stale_ids=%s",
        len(targets), len(succeeded), len(stale), str(succeeded), str(stale),
    )
    return stale
