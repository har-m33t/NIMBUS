"""SageMaker endpoint client for the ASL gloss model.

Contract (PROTOCOLS.md §7):
    Input tensor shape (1, T, 258) where 258 = leftHand(63) + rightHand(63)
    + pose(132). Missing landmarks → zero-padded.
    Output: {"tokens": [...], "confidence": float}

v1 uses T=1 (single INFER frame per invoke). If Member 3's model requires
temporal context (T>1), upgrade this module to maintain a rolling window
per sessionId in DynamoDB.
"""

from __future__ import annotations

import json
import os
from typing import Iterable

import boto3
from botocore.config import Config

from common.errors import SageMakerError
from common.schemas import Keypoints

ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT", "nimbus-prod-asl-endpoint")
TIMEOUT_MS = int(os.environ.get("SAGEMAKER_TIMEOUT_MS", "800"))

LEFT_HAND_LM = 21
RIGHT_HAND_LM = 21
POSE_LM = 33
FEATURES = LEFT_HAND_LM * 3 + RIGHT_HAND_LM * 3 + POSE_LM * 4  # 63+63+132 = 258

_runtime = None
_sagemaker = None


def _runtime_client():
    global _runtime
    if _runtime is None:
        cfg = Config(
            connect_timeout=max(0.2, TIMEOUT_MS / 1000 / 2),
            read_timeout=TIMEOUT_MS / 1000,
            retries={"max_attempts": 0},
        )
        _runtime = boto3.client("sagemaker-runtime", config=cfg)
    return _runtime


def _sagemaker_client():
    global _sagemaker
    if _sagemaker is None:
        _sagemaker = boto3.client("sagemaker")
    return _sagemaker


def _pad_hand(hand) -> list[float]:
    out: list[float] = []
    for lm in hand[:LEFT_HAND_LM]:
        out.extend([float(lm.x), float(lm.y), float(lm.z)])
    # zero-pad missing landmarks
    while len(out) < LEFT_HAND_LM * 3:
        out.append(0.0)
    return out


def _pad_pose(pose) -> list[float]:
    out: list[float] = []
    for lm in pose[:POSE_LM]:
        out.extend([float(lm.x), float(lm.y), float(lm.z), float(lm.visibility or 0.0)])
    while len(out) < POSE_LM * 4:
        out.append(0.0)
    return out


def flatten(keypoints: Keypoints) -> list[float]:
    """Build a (258,) feature vector from one INFER frame."""
    vec = (
        _pad_hand(keypoints.leftHand)
        + _pad_hand(keypoints.rightHand)
        + _pad_pose(keypoints.pose)
    )
    assert len(vec) == FEATURES, f"expected {FEATURES}, got {len(vec)}"
    return vec


def to_tensor(keypoints_list: Iterable[Keypoints]) -> list[list[list[float]]]:
    """Return shape (1, T, 258). v1 passes [current_frame]."""
    return [[flatten(k) for k in keypoints_list]]


def invoke(keypoints: Keypoints) -> dict:
    """Call the endpoint with T=1. Raises SageMakerError on any failure."""
    body = json.dumps({"instances": to_tensor([keypoints])})
    try:
        resp = _runtime_client().invoke_endpoint(
            EndpointName=ENDPOINT_NAME,
            ContentType="application/json",
            Accept="application/json",
            Body=body,
        )
        payload = json.loads(resp["Body"].read())
    except Exception as exc:  # includes ReadTimeoutError
        raise SageMakerError(str(exc)) from exc

    tokens = payload.get("tokens") or []
    confidence = float(payload.get("confidence", 0.0))
    return {"tokens": list(tokens), "confidence": confidence}


def is_in_service() -> bool:
    """Check endpoint status for cold-start gating (PROTOCOLS.md §4.3)."""
    try:
        resp = _sagemaker_client().describe_endpoint(EndpointName=ENDPOINT_NAME)
        return resp.get("EndpointStatus") == "InService"
    except Exception:
        return False
