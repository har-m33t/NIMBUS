"""Timed OpenCV webcam capture for the local desktop client."""

from __future__ import annotations

import logging
import time
from collections import deque

import cv2
import numpy as np

TARGET_FPS = 10
FRAME_INTERVAL_S = 1.0 / TARGET_FPS
DEFAULT_FRAME_WIDTH = 640
DEFAULT_FRAME_HEIGHT = 480

logger = logging.getLogger(__name__)


class VideoStream:
    """OpenCV-backed camera reader that enforces a minimum frame interval."""

    def __init__(self, camera_index: int = 0, target_fps: float = TARGET_FPS) -> None:
        if target_fps <= 0:
            raise ValueError("target_fps must be positive")

        self.camera_index = camera_index
        self.target_fps = float(target_fps)
        self.frame_interval_s = 1.0 / self.target_fps
        self._capture = cv2.VideoCapture(camera_index)
        if not self._capture.isOpened():
            raise RuntimeError(f"Cannot open camera {camera_index}")

        self._fps_timestamps: deque[float] = deque(maxlen=30)
        self._next_capture_at = time.monotonic()
        self._released = False
        self._frame_width = self._capture_dimension(cv2.CAP_PROP_FRAME_WIDTH, DEFAULT_FRAME_WIDTH)
        self._frame_height = self._capture_dimension(cv2.CAP_PROP_FRAME_HEIGHT, DEFAULT_FRAME_HEIGHT)

        # Prefer the freshest frame when the backend/UI loop lags briefly.
        self._capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def __enter__(self) -> "VideoStream":
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()

    def __iter__(self) -> "VideoStream":
        return self

    def __next__(self) -> tuple[np.ndarray, int]:
        if not self.is_open():
            raise StopIteration
        return self.read_frame()

    def is_open(self) -> bool:
        return not self._released and self._capture.isOpened()

    def read_frame(self) -> tuple[np.ndarray, int]:
        if not self.is_open():
            raise RuntimeError("Video stream is not open")

        now = time.monotonic()
        if now < self._next_capture_at:
            time.sleep(self._next_capture_at - now)

        ok, frame = self._capture.read()
        if not ok or frame is None:
            raise RuntimeError(f"Camera read failed for camera {self.camera_index}")

        self._frame_height, self._frame_width = frame.shape[:2]
        captured_at = time.monotonic()
        self._fps_timestamps.append(captured_at)

        scheduled_next = self._next_capture_at + self.frame_interval_s
        self._next_capture_at = max(scheduled_next, captured_at + self.frame_interval_s)

        return frame, time.time_ns()

    def blank_frame(self) -> np.ndarray:
        return np.zeros((self._frame_height, self._frame_width, 3), dtype=np.uint8)

    def get_fps(self) -> float:
        if len(self._fps_timestamps) < 2:
            return 0.0
        elapsed = self._fps_timestamps[-1] - self._fps_timestamps[0]
        if elapsed <= 0:
            return 0.0
        return (len(self._fps_timestamps) - 1) / elapsed

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._capture.release()

    def _capture_dimension(self, prop_id: int, fallback: int) -> int:
        try:
            value = int(self._capture.get(prop_id))
        except Exception:
            logger.debug("Failed to read capture property %s", prop_id, exc_info=True)
            value = 0
        return value if value > 0 else fallback
