"""
MediaPipe Holistic logic for extracting hand, pose, and face landmarks from frames.
"""
from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field

import cv2
import mediapipe as mp
import numpy as np

_log = logging.getLogger(__name__)

_FACE_CROP_MAX_W = 640
_FACE_CROP_MAX_H = 480
_FACE_CROP_PADDING = 0.20  # fractional padding around detected face bbox


@dataclass
class Landmark:
    x: float
    y: float
    z: float
    visibility: float | None = None


@dataclass
class Keypoints:
    leftHand: list[Landmark] = field(default_factory=list)
    rightHand: list[Landmark] = field(default_factory=list)
    pose: list[Landmark] = field(default_factory=list)


@dataclass
class ExtractResult:
    keypoints: Keypoints
    face_crop_b64: str | None  # base64 JPEG; None when no face detected or not requested


class MediaPipeExtractor:
    def __init__(self):
        self._holistic = mp.solutions.holistic.Holistic(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            refine_face_landmarks=True,
        )

    def extract(self, frame_bgr: np.ndarray, include_face_crop: bool) -> ExtractResult:
        """Process one BGR frame. Returns normalized keypoints + optional base64 face JPEG."""
        h, w = frame_bgr.shape[:2]
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        results = self._holistic.process(rgb)

        keypoints = Keypoints(
            leftHand=_hand_landmarks(results.left_hand_landmarks),
            rightHand=_hand_landmarks(results.right_hand_landmarks),
            pose=_pose_landmarks(results.pose_landmarks),
        )

        face_crop_b64: str | None = None
        if include_face_crop and results.face_landmarks:
            face_crop_b64 = _crop_face(frame_bgr, results.face_landmarks, w, h)

        return ExtractResult(keypoints=keypoints, face_crop_b64=face_crop_b64)

    def close(self):
        self._holistic.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _hand_landmarks(landmarks) -> list[Landmark]:
    if landmarks is None:
        return []
    return [
        Landmark(x=round(lm.x, 6), y=round(lm.y, 6), z=round(lm.z, 6))
        for lm in landmarks.landmark
    ]


def _pose_landmarks(landmarks) -> list[Landmark]:
    if landmarks is None:
        return []
    result = []
    for lm in landmarks.landmark:
        try:
            vis = lm.visibility if lm.HasField("visibility") else None
        except Exception:
            vis = float(lm.visibility) if hasattr(lm, "visibility") else None
        result.append(Landmark(
            x=round(lm.x, 6),
            y=round(lm.y, 6),
            z=round(lm.z, 6),
            visibility=round(vis, 4) if vis is not None else None,
        ))
    return result


def _crop_face(frame_bgr: np.ndarray, face_landmarks, w: int, h: int) -> str | None:
    """Crop face region from frame using landmark bounding box. Returns base64 JPEG or None."""
    xs = [lm.x for lm in face_landmarks.landmark]
    ys = [lm.y for lm in face_landmarks.landmark]

    x_min = max(0.0, min(xs) - _FACE_CROP_PADDING)
    x_max = min(1.0, max(xs) + _FACE_CROP_PADDING)
    y_min = max(0.0, min(ys) - _FACE_CROP_PADDING)
    y_max = min(1.0, max(ys) + _FACE_CROP_PADDING)

    px1, px2 = int(x_min * w), int(x_max * w)
    py1, py2 = int(y_min * h), int(y_max * h)

    if px2 <= px1 or py2 <= py1:
        return None

    crop = frame_bgr[py1:py2, px1:px2]
    crop_h, crop_w = crop.shape[:2]
    if crop_h == 0 or crop_w == 0:
        return None

    scale = min(_FACE_CROP_MAX_W / crop_w, _FACE_CROP_MAX_H / crop_h, 1.0)
    if scale < 1.0:
        crop = cv2.resize(
            crop,
            (int(crop_w * scale), int(crop_h * scale)),
            interpolation=cv2.INTER_AREA,
        )

    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        _log.warning("cv2.imencode failed for face crop")
        return None

    return base64.b64encode(buf.tobytes()).decode("ascii")
