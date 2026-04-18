"""
Unit tests for skeleton/inference.py — 5 core contract cases.
Run with: pytest tests/ -v
"""
from __future__ import annotations

import json
import sys
import os
import types
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Path setup — make skeleton/inference importable without installing
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skeleton"))

# Stub heavy optional deps before import so tests run without GPU / AWS creds
_torch_stub = types.ModuleType("torch")
_torch_stub.device = lambda *a, **kw: "cpu"
_torch_stub.cuda = MagicMock()
_torch_stub.cuda.is_available = lambda: False
_torch_stub.load = MagicMock()
_torch_stub.no_grad = MagicMock(return_value=MagicMock(__enter__=lambda s, *a: s, __exit__=lambda s, *a: None))

def _mock_tensor_with_ops(*args, **kw):
    mock = MagicMock()
    mock.mean = MagicMock(return_value=MagicMock(item=lambda: 0.75))
    mock.max = MagicMock(return_value=(MagicMock(item=lambda: 0), MagicMock(item=lambda: 0)))
    mock.to = MagicMock(return_value=mock)
    return mock

_torch_stub.tensor = _mock_tensor_with_ops
_torch_stub.softmax = MagicMock(return_value=MagicMock(max=lambda dim: (MagicMock(mean=lambda: MagicMock(item=lambda: 0.75)), MagicMock(item=lambda: 0))))

_nn = types.ModuleType("torch.nn")
_nn.Module = object
_torch_stub.nn = _nn
sys.modules.setdefault("torch", _torch_stub)
sys.modules.setdefault("torch.nn", _nn)

_boto3_stub = MagicMock()
sys.modules.setdefault("boto3", _boto3_stub)

import inference  # noqa: E402  (imported after path/stub setup)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_payload(n_frames: int = 1) -> str:
    """Return a valid application/json request body for n_frames."""
    flat = [0.1] * (258 * n_frames)
    return json.dumps({"instances": [{"keypoints": flat}]})


# ---------------------------------------------------------------------------
# Test 1 — input_fn: valid payload produces correct shape
# ---------------------------------------------------------------------------

def test_input_fn_returns_correct_shape():
    """input_fn converts a valid JSON payload to shape (1, T, 258)."""
    T = 4
    result = inference.input_fn(_make_payload(T), "application/json")
    assert isinstance(result, np.ndarray), "expected numpy ndarray"
    assert result.shape == (1, T, 258), f"expected (1, {T}, 258), got {result.shape}"
    assert result.dtype == np.float32


# ---------------------------------------------------------------------------
# Test 2 — input_fn: rejects unsupported content type
# ---------------------------------------------------------------------------

def test_input_fn_rejects_unsupported_content_type():
    """input_fn raises ValueError for content types other than application/json."""
    with pytest.raises(ValueError, match="Unsupported content_type"):
        inference.input_fn(_make_payload(), "text/plain")


# ---------------------------------------------------------------------------
# Test 3 — input_fn: rejects keypoints length not divisible by 258
# ---------------------------------------------------------------------------

def test_input_fn_rejects_wrong_keypoints_length():
    """input_fn raises ValueError when keypoints length is not divisible by 258."""
    bad_body = json.dumps({"instances": [{"keypoints": [0.5] * 100}]})
    with pytest.raises(ValueError, match="not divisible by"):
        inference.input_fn(bad_body, "application/json")


# ---------------------------------------------------------------------------
# Test 4 — predict_fn: falls back to [UNKNOWN_SIGN] on model exception
# ---------------------------------------------------------------------------

def test_predict_fn_falls_back_on_exception():
    """predict_fn returns [UNKNOWN_SIGN] with confidence 0.0 when model errors."""
    broken_model = MagicMock()
    broken_model.parameters = MagicMock(return_value=iter([MagicMock(device="cpu")]))
    broken_model.side_effect = RuntimeError("CUDA OOM")

    input_arr = np.zeros((1, 1, 258), dtype=np.float32)
    result = inference.predict_fn(input_arr, (broken_model, ["HELLO"]))

    assert result["tokens"] == ["[UNKNOWN_SIGN]"]
    assert result["confidence"] == 0.0


# ---------------------------------------------------------------------------
# Test 5 — output_fn: tokens are null when confidence is below threshold
# ---------------------------------------------------------------------------

def test_output_fn_null_tokens_below_threshold():
    """output_fn serialises tokens as null when confidence < CONFIDENCE_THRESHOLD (0.60)."""
    prediction = {"tokens": ["HELLO"], "confidence": 0.45, "_latency_ms": 10.0}

    with patch.object(inference, "_cloudwatch", return_value=MagicMock()):
        body, content_type = inference.output_fn(prediction, "application/json")

    assert content_type == "application/json"
    parsed = json.loads(body)
    tokens = parsed["tokens"]
    assert tokens is None, f"expected null tokens below threshold, got {tokens!r}"
