from __future__ import annotations

import numpy as np
import pytest

from capture.adapter import (
    FEATURES_225,
    FEATURES_258,
    FEATURES_63,
    adapt_258_to_225,
    adapt_258_to_63,
    adapt_features,
)


def test_adapt_258_to_225_drops_pose_visibility() -> None:
    frame = np.arange(FEATURES_258, dtype=np.float32)

    adapted = adapt_258_to_225(frame)

    assert adapted.shape == (FEATURES_225,)
    assert np.array_equal(adapted[:126], frame[:126])
    expected_pose = frame[126:].reshape(33, 4)[:, :3].reshape(99)
    assert np.array_equal(adapted[126:], expected_pose)


def test_adapt_258_to_225_preserves_leading_dimensions() -> None:
    frames = np.arange(2 * 3 * FEATURES_258, dtype=np.float32).reshape(2, 3, FEATURES_258)

    adapted = adapt_258_to_225(frames)

    assert adapted.shape == (2, 3, FEATURES_225)


def test_adapt_258_to_63_prefers_populated_hand() -> None:
    # Only the LEFT slot has data → adapter returns the left slice.
    left_only = np.zeros(FEATURES_258, dtype=np.float32)
    left_only[:FEATURES_63] = np.linspace(0.2, 0.8, FEATURES_63)
    adapted = adapt_258_to_63(left_only)
    assert adapted.shape == (FEATURES_63,)
    assert np.array_equal(adapted, left_only[:FEATURES_63])

    # Only the RIGHT slot has data (typical right-handed signer on an
    # unflipped webcam) → adapter returns the right slice, not zeros.
    right_only = np.zeros(FEATURES_258, dtype=np.float32)
    right_only[FEATURES_63:2 * FEATURES_63] = np.linspace(0.2, 0.8, FEATURES_63)
    adapted = adapt_258_to_63(right_only)
    assert adapted.shape == (FEATURES_63,)
    assert np.array_equal(adapted, right_only[FEATURES_63:2 * FEATURES_63])

    # Batched input keeps leading dimensions.
    batch = np.stack([left_only, right_only])
    adapted_batch = adapt_258_to_63(batch)
    assert adapted_batch.shape == (2, FEATURES_63)
    assert np.array_equal(adapted_batch[0], left_only[:FEATURES_63])
    assert np.array_equal(adapted_batch[1], right_only[FEATURES_63:2 * FEATURES_63])


def test_adapt_features_passthrough_for_matching_width() -> None:
    frame = np.arange(FEATURES_258, dtype=np.float32)

    adapted = adapt_features(frame, FEATURES_258)

    assert np.array_equal(adapted, frame)


def test_adapt_features_rejects_unsupported_width() -> None:
    with pytest.raises(ValueError, match="Unsupported target width"):
        adapt_features(np.zeros(FEATURES_258, dtype=np.float32), 266)


def test_adapters_reject_non_258_inputs() -> None:
    with pytest.raises(ValueError, match="Expected trailing feature width 258"):
        adapt_258_to_225(np.zeros(FEATURES_225, dtype=np.float32))

    with pytest.raises(ValueError, match="Expected trailing feature width 258"):
        adapt_258_to_63(np.zeros(FEATURES_63, dtype=np.float32))
