"""
Handles OpenCV webcam integration and frame retrieval.
"""
from __future__ import annotations

import time

import cv2
import numpy as np

_TARGET_FPS = 10
_FRAME_INTERVAL = 1.0 / _TARGET_FPS


class VideoStream:
    def __init__(self, device_index: int = 0):
        self._cap = cv2.VideoCapture(device_index)
        if not self._cap.isOpened():
            raise RuntimeError(f"Cannot open webcam device {device_index}")
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    def read_frame(self) -> np.ndarray | None:
        """Read one frame; returns BGR ndarray or None on failure."""
        ok, frame = self._cap.read()
        return frame if ok else None

    def frames_at_10fps(self):
        """Yield frames at ≈10 FPS, blocking between yields to maintain rate."""
        next_tick = time.monotonic()
        while True:
            frame = self.read_frame()
            if frame is not None:
                yield frame
            next_tick += _FRAME_INTERVAL
            delay = next_tick - time.monotonic()
            if delay > 0:
                time.sleep(delay)

    def release(self):
        self._cap.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.release()
