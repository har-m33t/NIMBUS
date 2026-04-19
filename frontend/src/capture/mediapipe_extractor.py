"""MediaPipe Tasks-API extractor for webcam frames.

The legacy ``mediapipe.solutions.holistic`` pipeline was removed from the
mediapipe wheels shipping on Python 3.13 (>= 0.10.30). This module replaces it
with the modern ``mediapipe.tasks.vision`` API, running ``HandLandmarker`` and
``PoseLandmarker`` side-by-side to reproduce the Holistic output we rely on.

The 258-feature tensor contract (PROTOCOLS.md §7) is preserved exactly:
    left hand  (21 × 3)  = 63
    right hand (21 × 3)  = 63
    pose       (33 × 4)  = 132
                        ---
                         258
"""

from __future__ import annotations

import base64
import logging
import os
import time
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np

import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision

HAND_LANDMARKS = 21
POSE_LANDMARKS = 33
FEATURES_PER_FRAME = 258

MAX_FACE_WIDTH = 640
MAX_FACE_HEIGHT = 480
FACE_PADDING_RATIO = 0.18

# MediaPipe Pose landmarks 0-10 are facial (nose, eyes, ears, mouth). Using
# these lets us keep the face-crop feature alive without instantiating a
# separate FaceLandmarker.
POSE_FACE_LANDMARK_COUNT = 11

_DEFAULT_CACHE_DIR = Path.home() / ".cache" / "nimbus" / "mediapipe_models"
MODEL_CACHE_DIR = Path(os.environ.get("NIMBUS_MEDIAPIPE_MODEL_DIR") or _DEFAULT_CACHE_DIR)

HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/latest/hand_landmarker.task"
)
POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/latest/pose_landmarker_lite.task"
)
HAND_MODEL_FILE = "hand_landmarker.task"
POSE_MODEL_FILE = "pose_landmarker_lite.task"

logger = logging.getLogger(__name__)


def _download_model(url: str, destination: Path) -> Path:
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = destination.with_suffix(destination.suffix + ".part")
    logger.info("Downloading MediaPipe model: %s -> %s", url, destination)
    try:
        urllib.request.urlretrieve(url, tmp_path)
        tmp_path.replace(destination)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise
    return destination


class MediaPipeExtractor:
    """Extracts 258-feature vectors and optional face crops via Tasks API."""

    def __init__(
        self,
        min_detection_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
        model_cache_dir: Path | None = None,
    ) -> None:
        cache_dir = Path(model_cache_dir) if model_cache_dir else MODEL_CACHE_DIR
        hand_model_path = _download_model(HAND_MODEL_URL, cache_dir / HAND_MODEL_FILE)
        pose_model_path = _download_model(POSE_MODEL_URL, cache_dir / POSE_MODEL_FILE)

        running_mode = mp_vision.RunningMode.VIDEO

        self._hand_landmarker = mp_vision.HandLandmarker.create_from_options(
            mp_vision.HandLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(hand_model_path)),
                running_mode=running_mode,
                num_hands=2,
                min_hand_detection_confidence=float(min_detection_confidence),
                min_hand_presence_confidence=float(min_detection_confidence),
                min_tracking_confidence=float(min_tracking_confidence),
            )
        )

        self._pose_landmarker = mp_vision.PoseLandmarker.create_from_options(
            mp_vision.PoseLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(pose_model_path)),
                running_mode=running_mode,
                num_poses=1,
                min_pose_detection_confidence=float(min_detection_confidence),
                min_pose_presence_confidence=float(min_detection_confidence),
                min_tracking_confidence=float(min_tracking_confidence),
            )
        )

        self._start_ns = time.monotonic_ns()
        self._last_timestamp_ms = -1

    def __enter__(self) -> "MediaPipeExtractor":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        for attr in ("_hand_landmarker", "_pose_landmarker"):
            landmarker = getattr(self, attr, None)
            if landmarker is None:
                continue
            try:
                landmarker.close()
            except Exception:
                logger.debug("Failed to close %s", attr, exc_info=True)

    def process(self, bgr_frame: np.ndarray) -> tuple[np.ndarray, dict | None]:
        if bgr_frame is None or not isinstance(bgr_frame, np.ndarray) or bgr_frame.ndim != 3:
            return self.zero_vector(), None

        try:
            rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            timestamp_ms = self._next_timestamp_ms()

            hand_result = self._hand_landmarker.detect_for_video(mp_image, timestamp_ms)
            pose_result = self._pose_landmarker.detect_for_video(mp_image, timestamp_ms)

            left_hand, right_hand = self._split_hands(hand_result)
            pose_landmarks = None
            if pose_result is not None and getattr(pose_result, "pose_landmarks", None):
                pose_landmarks = pose_result.pose_landmarks[0]

            features = self._build_feature_vector(left_hand, right_hand, pose_landmarks)
            context = {
                "left_hand_landmarks": left_hand,
                "right_hand_landmarks": right_hand,
                "pose_landmarks": pose_landmarks,
            }
            return features, context
        except Exception:
            logger.exception("MediaPipe Tasks processing failed")
            return self.zero_vector(), None

    def extract_face_crop(self, bgr_frame: np.ndarray, results: dict | None) -> str | None:
        if (
            bgr_frame is None
            or not isinstance(bgr_frame, np.ndarray)
            or bgr_frame.ndim != 3
            or not results
        ):
            return None

        pose_landmarks = results.get("pose_landmarks")
        if not pose_landmarks:
            return None

        try:
            height, width = bgr_frame.shape[:2]
            face_points = list(pose_landmarks)[:POSE_FACE_LANDMARK_COUNT]
            if not face_points:
                return None

            xs = [self._safe_pixel_coord(getattr(pt, "x", 0.0), width) for pt in face_points]
            ys = [self._safe_pixel_coord(getattr(pt, "y", 0.0), height) for pt in face_points]
            x_min, x_max = min(xs), max(xs)
            y_min, y_max = min(ys), max(ys)
            if x_max <= x_min or y_max <= y_min:
                return None

            pad_x = int((x_max - x_min) * FACE_PADDING_RATIO)
            pad_y = int((y_max - y_min) * FACE_PADDING_RATIO)
            left = max(0, x_min - pad_x)
            top = max(0, y_min - pad_y)
            right = min(width, x_max + pad_x)
            bottom = min(height, y_max + pad_y)

            face_crop = bgr_frame[top:bottom, left:right]
            if face_crop.size == 0:
                return None

            crop_h, crop_w = face_crop.shape[:2]
            scale = min(MAX_FACE_WIDTH / crop_w, MAX_FACE_HEIGHT / crop_h, 1.0)
            if scale < 1.0:
                resized = cv2.resize(
                    face_crop,
                    (max(1, int(crop_w * scale)), max(1, int(crop_h * scale))),
                    interpolation=cv2.INTER_AREA,
                )
            else:
                resized = face_crop

            ok, encoded = cv2.imencode(".jpg", resized, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return None

            return base64.b64encode(encoded.tobytes()).decode("ascii")
        except Exception:
            logger.warning("Face crop extraction failed", exc_info=True)
            return None

    def draw_landmarks(self, bgr_frame: np.ndarray, results: dict | None) -> None:
        if bgr_frame is None or not results:
            return
        try:
            height, width = bgr_frame.shape[:2]
            self._draw_points(bgr_frame, results.get("left_hand_landmarks"), width, height, (0, 220, 60))
            self._draw_points(bgr_frame, results.get("right_hand_landmarks"), width, height, (0, 220, 60))
            self._draw_points(bgr_frame, results.get("pose_landmarks"), width, height, (0, 180, 255))
        except Exception:
            logger.warning("Landmark drawing failed", exc_info=True)

    @classmethod
    def zero_vector(cls) -> np.ndarray:
        return np.zeros(FEATURES_PER_FRAME, dtype=np.float32)

    def _next_timestamp_ms(self) -> int:
        # detect_for_video requires strictly monotonic timestamps per landmarker.
        elapsed_ms = (time.monotonic_ns() - self._start_ns) // 1_000_000
        ts = max(self._last_timestamp_ms + 1, int(elapsed_ms))
        self._last_timestamp_ms = ts
        return ts

    @staticmethod
    def _split_hands(hand_result: Any) -> tuple[list | None, list | None]:
        """Route detected hands into left/right slots using handedness labels."""
        if hand_result is None:
            return None, None
        landmarks_list = list(getattr(hand_result, "hand_landmarks", []) or [])
        if not landmarks_list:
            return None, None

        handedness = list(getattr(hand_result, "handedness", []) or [])
        left: list | None = None
        right: list | None = None

        for idx, landmarks in enumerate(landmarks_list):
            label = ""
            if idx < len(handedness) and handedness[idx]:
                label = (getattr(handedness[idx][0], "category_name", "") or "").upper()

            if label == "LEFT" and left is None:
                left = landmarks
            elif label == "RIGHT" and right is None:
                right = landmarks
            elif left is None:
                left = landmarks
            elif right is None:
                right = landmarks

        return left, right

    def _build_feature_vector(
        self,
        left_hand: list | None,
        right_hand: list | None,
        pose_landmarks: list | None,
    ) -> np.ndarray:
        left = self._extract_hand(left_hand)
        right = self._extract_hand(right_hand)
        pose = self._extract_pose(pose_landmarks)
        return np.asarray(left + right + pose, dtype=np.float32)

    @classmethod
    def _extract_hand(cls, hand_landmarks: list | None) -> list[float]:
        if not hand_landmarks:
            return [0.0] * (HAND_LANDMARKS * 3)

        coords: list[float] = []
        for landmark in list(hand_landmarks)[:HAND_LANDMARKS]:
            coords.extend(
                [
                    cls._normalized_value(getattr(landmark, "x", 0.0)),
                    cls._normalized_value(getattr(landmark, "y", 0.0)),
                    cls._float_value(getattr(landmark, "z", 0.0)),
                ]
            )
        while len(coords) < HAND_LANDMARKS * 3:
            coords.append(0.0)
        return coords

    @classmethod
    def _extract_pose(cls, pose_landmarks: list | None) -> list[float]:
        if not pose_landmarks:
            return [0.0] * (POSE_LANDMARKS * 4)

        coords: list[float] = []
        for landmark in list(pose_landmarks)[:POSE_LANDMARKS]:
            coords.extend(
                [
                    cls._normalized_value(getattr(landmark, "x", 0.0)),
                    cls._normalized_value(getattr(landmark, "y", 0.0)),
                    cls._float_value(getattr(landmark, "z", 0.0)),
                    cls._normalized_value(getattr(landmark, "visibility", 0.0)),
                ]
            )
        while len(coords) < POSE_LANDMARKS * 4:
            coords.append(0.0)
        return coords

    @staticmethod
    def _draw_points(
        frame: np.ndarray,
        landmarks: list | None,
        width: int,
        height: int,
        color: tuple[int, int, int],
    ) -> None:
        if not landmarks:
            return
        for landmark in landmarks:
            x = int(np.clip(float(getattr(landmark, "x", 0.0) or 0.0), 0.0, 1.0) * width)
            y = int(np.clip(float(getattr(landmark, "y", 0.0) or 0.0), 0.0, 1.0) * height)
            cv2.circle(frame, (x, y), 3, color, -1, cv2.LINE_AA)

    @staticmethod
    def _normalized_value(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not np.isfinite(numeric):
            return 0.0
        return float(np.clip(numeric, 0.0, 1.0))

    @staticmethod
    def _float_value(value: Any) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not np.isfinite(numeric):
            return 0.0
        return numeric

    @classmethod
    def _safe_pixel_coord(cls, value: Any, limit: int) -> int:
        if limit <= 0:
            return 0
        normalized = cls._normalized_value(value)
        return int(normalized * limit)
