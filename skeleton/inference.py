"""
NIMBUS ASL Inference — SageMaker endpoint entry point.
Loaded by the SageMaker serving stack via model_fn / input_fn / predict_fn / output_fn.
All shapes and dtypes must match PROTOCOLS.md §7 (feature=258 per frame).
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

import boto3
import numpy as np
import torch

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CONFIDENCE_THRESHOLD = 0.60
FEATURES_PER_FRAME = 258

_cw_client: Any = None
_request_ctx = threading.local()


def _cloudwatch() -> Any:
    global _cw_client
    if _cw_client is None:
        _cw_client = boto3.client(
            "cloudwatch", region_name=os.environ.get("AWS_REGION", "us-east-1")
        )
    return _cw_client


# ---------------------------------------------------------------------------
# SageMaker serving interface (four required hooks)
# ---------------------------------------------------------------------------

def model_fn(model_dir: str) -> tuple[torch.nn.Module, list[str]]:
    """Load the trained ASL Transformer from `model_dir` and return it.

    SageMaker calls this once at container start. The returned object is passed
    to `predict_fn` on every request.

    Args:
        model_dir: Absolute path to the directory where SageMaker extracted the
            model artifact (tar.gz from S3 `nimbus-prod-model-artifacts`).

    Returns:
        A PyTorch model set to eval mode, moved to the available device.
    """
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model_path = os.path.join(model_dir, "model.pth")
    model: torch.nn.Module = torch.load(model_path, map_location=device)
    model.eval()

    label_map_path = os.path.join(model_dir, "label_map.json")
    with open(label_map_path) as fh:
        label_map: list[str] = json.load(fh)

    logger.info("Model loaded on %s; vocabulary size=%d", device, len(label_map))
    return model, label_map


def input_fn(request_body: str | bytes, content_type: str) -> np.ndarray:
    """Deserialise and validate an inference request.

    Accepts `application/json`. Expects the Lambda payload shape defined in
    contracts.md §2: a flat float array that can be reshaped to (1, T, 258).

    Args:
        request_body: Raw HTTP body from the `invoke_endpoint` call.
        content_type: MIME type; must be `application/json`.

    Returns:
        Float32 numpy array of shape (1, T, 258), zero-padded for absent hands.

    Raises:
        ValueError: If content_type is unsupported or keypoint dimensions are wrong.
    """
    _request_ctx.start_ms = time.time() * 1000

    if content_type != "application/json":
        raise ValueError(f"Unsupported content_type: {content_type!r}; expected application/json")

    try:
        body = json.loads(request_body if isinstance(request_body, str) else request_body.decode())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Malformed JSON in request body: {exc}") from exc
    instances = body.get("instances", [])
    if not instances:
        raise ValueError("Request body missing 'instances' key or empty list")

    flat: list[float] = instances[0]["keypoints"]
    if len(flat) % FEATURES_PER_FRAME != 0:
        raise ValueError(
            f"keypoints length {len(flat)} is not divisible by {FEATURES_PER_FRAME}"
        )

    t_frames = len(flat) // FEATURES_PER_FRAME
    arr = np.array(flat, dtype=np.float32).reshape(1, t_frames, FEATURES_PER_FRAME)
    return arr


def predict_fn(
    input_data: np.ndarray,
    model: tuple[torch.nn.Module, list[str]],
) -> dict[str, Any]:
    """Run the ASL Transformer forward pass.

    Args:
        input_data: Float32 array (1, T, 258) from `input_fn`.
        model: (model, label_map) tuple from `model_fn`.

    Returns:
        Dict with keys `tokens` (list[str]), `confidence` (float ∈ [0, 1]),
        and `_latency_ms` (float, internal — consumed by output_fn).
        On any exception, returns `{"tokens": ["[UNKNOWN_SIGN]"], "confidence": 0.0, "_latency_ms": 0.0}`.
    """
    net, label_map = model
    device = next(net.parameters()).device

    try:
        tensor = torch.tensor(input_data, dtype=torch.float32).to(device)
        with torch.no_grad():
            logits = net(tensor)  # shape: (1, T_out, vocab)

        probs = torch.softmax(logits, dim=-1)
        confidences, indices = probs.max(dim=-1)  # (1, T_out)

        seq_confidence = float(confidences[0].mean().item())
        tokens = [label_map[idx.item()] for idx in indices[0]]

        latency_ms = time.time() * 1000 - getattr(_request_ctx, "start_ms", 0.0)
        return {"tokens": tokens, "confidence": round(seq_confidence, 3), "_latency_ms": latency_ms}

    except Exception as exc:
        logger.error("Inference failed: %s", exc, exc_info=True)
        return {"tokens": ["[UNKNOWN_SIGN]"], "confidence": 0.0, "_latency_ms": 0.0}


def output_fn(
    prediction: dict[str, Any],
    accept: str,
) -> tuple[str, str]:
    """Serialise the prediction dict to the response body.

    Args:
        prediction: Output of `predict_fn`.
        accept: Client-requested MIME type (must be `application/json`).

    Returns:
        Tuple of (response_body_str, content_type_str).

    Raises:
        ValueError: If `accept` is not `application/json`.
    """
    if accept != "application/json":
        raise ValueError(f"Unsupported accept type: {accept!r}; expected application/json")

    latency_ms: float = prediction.pop("_latency_ms", 0.0)

    try:
        _cloudwatch().put_metric_data(
            Namespace="ASL/Pipeline",
            MetricData=[
                {
                    "MetricName": "KeypointToGlossMs",
                    "Value": latency_ms,
                    "Unit": "Milliseconds",
                }
            ],
        )
    except Exception as cw_exc:
        logger.warning("CloudWatch put_metric_data failed: %s", cw_exc)

    confidence = prediction["confidence"]
    tokens = prediction["tokens"] if confidence >= CONFIDENCE_THRESHOLD else None

    body = json.dumps({"tokens": tokens, "confidence": confidence})
    return body, "application/json"
