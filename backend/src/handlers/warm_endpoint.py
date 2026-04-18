"""NIMBUS_PROD_WarmEndpoint — keeps SageMaker endpoint warm on a schedule.

Runs every 5 minutes to prevent 30–90s cold starts (PROTOCOLS.md §4.3).
Sends a zero-padded dummy payload; the model response is discarded.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3

ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT", "nimbus-prod-asl-endpoint")
FEATURES = 258  # leftHand(63) + rightHand(63) + pose(132)

_runtime = None


def _client():
    global _runtime
    if _runtime is None:
        _runtime = boto3.client("sagemaker-runtime")
    return _runtime


def handler(_event: dict, _context: Any) -> dict:
    try:
        body = json.dumps({"instances": [[[0.0] * FEATURES]]})
        _client().invoke_endpoint(
            EndpointName=ENDPOINT_NAME,
            ContentType="application/json",
            Accept="application/json",
            Body=body,
        )
        return {"statusCode": 200, "body": "warm"}
    except Exception as exc:
        # Non-fatal: endpoint may be deploying; log and return 200 so EventBridge
        # does not trigger alarm on repeated failures during normal startup.
        print(f"WarmEndpoint: {exc}")
        return {"statusCode": 200, "body": "skipped"}
