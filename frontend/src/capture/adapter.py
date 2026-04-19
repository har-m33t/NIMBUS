from __future__ import annotations

import numpy as np

FEATURES_258 = 258
FEATURES_225 = 225
FEATURES_63 = 63
POSE_LANDMARKS = 33
POSE_FEATURES_WITH_VISIBILITY = 4
POSE_FEATURES_NO_VISIBILITY = 3


def _coerce_258(vec: np.ndarray) -> np.ndarray:
    arr = np.asarray(vec, dtype=np.float32)
    if arr.shape[-1] != FEATURES_258:
        raise ValueError(f"Expected trailing feature width {FEATURES_258}, got {arr.shape[-1]}")
    return arr


def adapt_258_to_225(vec: np.ndarray) -> np.ndarray:
    """Drop pose visibility values to match 225-feature pose models."""
    arr = _coerce_258(vec)
    left = arr[..., :63]
    right = arr[..., 63:126]
    pose = arr[..., 126:].reshape(
        *arr.shape[:-1],
        POSE_LANDMARKS,
        POSE_FEATURES_WITH_VISIBILITY,
    )
    pose_xyz = pose[..., :POSE_FEATURES_NO_VISIBILITY].reshape(*arr.shape[:-1], 99)
    return np.concatenate((left, right, pose_xyz), axis=-1)


def adapt_258_to_63(vec: np.ndarray) -> np.ndarray:
    """Select the populated hand for single-hand models.

    MediaPipe Tasks API reports handedness from the raw (unflipped) image, so
    right-handed signers normally land in the second 63-block and left-handed
    signers in the first. Hard-coding the leading slice feeds zeros to the
    classifier whenever only the right hand is visible, which for the current
    ASL-alphabet ONNX model collapses to "M" at ~91% confidence (the no-signal
    prior). We instead pick whichever hand slot carries more energy per frame.
    """
    arr = _coerce_258(vec)
    left = arr[..., :FEATURES_63]
    right = arr[..., FEATURES_63:2 * FEATURES_63]
    left_energy = np.sum(np.abs(left), axis=-1, keepdims=True)
    right_energy = np.sum(np.abs(right), axis=-1, keepdims=True)
    return np.where(right_energy > left_energy, right, left)


def adapt_features(vec: np.ndarray, target_width: int) -> np.ndarray:
    """Route the repo's 258-feature tensor into a known compatible model width."""
    arr = _coerce_258(vec)
    if target_width == FEATURES_258:
        return arr
    if target_width == FEATURES_225:
        return adapt_258_to_225(arr)
    if target_width == FEATURES_63:
        return adapt_258_to_63(arr)
    raise ValueError(
        f"Unsupported target width {target_width}. Expected one of: "
        f"{FEATURES_258}, {FEATURES_225}, {FEATURES_63}."
    )
