from __future__ import annotations

import base64
from types import SimpleNamespace

import cv2
import numpy as np

from capture.mediapipe_extractor import MediaPipeExtractor


def _landmark(x: float, y: float, z: float, visibility: float | None = None) -> SimpleNamespace:
    if visibility is None:
        return SimpleNamespace(x=x, y=y, z=z)
    return SimpleNamespace(x=x, y=y, z=z, visibility=visibility)


def test_process_invalid_frame_returns_zero_vector() -> None:
    extractor = MediaPipeExtractor.__new__(MediaPipeExtractor)

    keypoints, results = extractor.process(None)

    assert results is None
    assert keypoints.shape == (258,)
    assert keypoints.dtype == np.float32
    assert np.allclose(keypoints, 0.0)


def test_extract_keypoints_zero_pads_missing_landmarks() -> None:
    extractor = MediaPipeExtractor.__new__(MediaPipeExtractor)
    left = [_landmark(0.1, 0.2, -0.3)]
    right = None
    pose = [_landmark(0.6, 0.7, -0.1, 0.8)]

    keypoints = extractor._build_feature_vector(left, right, pose)

    assert keypoints.shape == (258,)
    assert keypoints.dtype == np.float32
    assert np.allclose(keypoints[0:3], [0.1, 0.2, -0.3])
    assert np.count_nonzero(keypoints[3:63]) == 0
    assert np.count_nonzero(keypoints[63:126]) == 0
    assert np.allclose(keypoints[126:130], [0.6, 0.7, -0.1, 0.8])


def test_extract_keypoints_sanitizes_non_finite_values() -> None:
    extractor = MediaPipeExtractor.__new__(MediaPipeExtractor)
    left = [_landmark(float("nan"), float("inf"), float("-inf"))]
    keypoints = extractor._build_feature_vector(left, None, None)

    assert np.allclose(keypoints[0:3], [0.0, 0.0, 0.0])


def test_extract_face_crop_returns_base64_jpeg() -> None:
    extractor = MediaPipeExtractor.__new__(MediaPipeExtractor)
    frame = np.full((120, 160, 3), 200, dtype=np.uint8)
    results = {
        "pose_landmarks": [
            _landmark(0.30, 0.25, 0.0),
            _landmark(0.70, 0.25, 0.0),
            _landmark(0.30, 0.75, 0.0),
            _landmark(0.70, 0.75, 0.0),
        ]
    }

    encoded = extractor.extract_face_crop(frame, results)

    assert encoded is not None
    decoded = base64.b64decode(encoded)
    image = cv2.imdecode(np.frombuffer(decoded, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    assert image.size > 0


def test_extract_face_crop_handles_bad_landmarks() -> None:
    extractor = MediaPipeExtractor.__new__(MediaPipeExtractor)
    frame = np.full((120, 160, 3), 200, dtype=np.uint8)
    results = {
        "pose_landmarks": [_landmark(float("nan"), float("nan"), 0.0)]
    }

    encoded = extractor.extract_face_crop(frame, results)

    assert encoded is None
