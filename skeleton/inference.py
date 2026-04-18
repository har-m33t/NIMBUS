"""
NIMBUS ASL Inference — SageMaker endpoint entry point.
Loaded by the SageMaker serving stack via model_fn / input_fn / predict_fn / output_fn.
All shapes and dtypes must match PROTOCOLS.md §7 (feature=258 per frame).
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import torch


# ---------------------------------------------------------------------------
# SageMaker serving interface (four required hooks)
# ---------------------------------------------------------------------------

def model_fn(model_dir: str) -> Any:
    """Load the trained ASL Transformer from `model_dir` and return it.

    SageMaker calls this once at container start. The returned object is passed
    to `predict_fn` on every request.

    Args:
        model_dir: Absolute path to the directory where SageMaker extracted the
            model artifact (tar.gz from S3 `nimbus-prod-model-artifacts`).

    Returns:
        A PyTorch model set to eval mode, moved to the available device.
    """
    ...


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
    ...


def predict_fn(input_data: np.ndarray, model: Any) -> dict[str, Any]:
    """Run the ASL Transformer forward pass.

    Args:
        input_data: Float32 tensor (1, T, 258) from `input_fn`.
        model: Loaded model from `model_fn`.

    Returns:
        Dict with keys `tokens` (list[str]) and `confidence` (float ∈ [0, 1]).
        On any exception, returns `{"tokens": ["[UNKNOWN_SIGN]"], "confidence": 0.0}`.
    """
    ...


def output_fn(prediction: dict[str, Any], accept: str) -> tuple[str, str]:
    """Serialise the prediction dict to the response body.

    Args:
        prediction: Output of `predict_fn`.
        accept: Client-requested MIME type (must be `application/json`).

    Returns:
        Tuple of (response_body_str, content_type_str).

    Raises:
        ValueError: If `accept` is not `application/json`.
    """
    ...
