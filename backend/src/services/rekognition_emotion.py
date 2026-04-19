"""Amazon Rekognition emotion detection (PROTOCOLS.md §3.2).

Called once per 10 keypoint frames with a JPEG face crop from the frontend.
Returns the dominant emotion and a full probability map.

Fallback contract (PROTOCOLS §4.1): any exception or empty detection → CALM.
"""
from __future__ import annotations

import logging
import os

import boto3
from botocore.config import Config

_log = logging.getLogger(__name__)

_REGION = os.environ.get("AWS_REGION", "us-west-2")
_CFG = Config(retries={"max_attempts": 2, "mode": "standard"}, read_timeout=5)

# Rekognition emotion type → PROTOCOLS EmotionLabel (PROTOCOLS.md §1.2)
_LABEL_MAP: dict[str, str] = {
    "HAPPY":     "HAPPY",
    "SAD":       "SAD",
    "ANGRY":     "ANGRY",
    "CALM":      "CALM",
    "SURPRISED": "SURPRISED",
    "FEAR":      "FEAR",
    "DISGUSTED": "DISGUSTED",
    "CONFUSED":  "CONFUSED",
}
_DEFAULT = "CALM"
_DEFAULT_RESULT: tuple[str, float, dict[str, float]] = (_DEFAULT, 1.0, {_DEFAULT: 1.0})

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("rekognition", region_name=_REGION, config=_CFG)
    return _client


def detect_emotion(
    face_jpeg_bytes: bytes,
) -> tuple[str, float, dict[str, float]]:
    """Detect emotion from a raw JPEG image.

    Returns (dominant_label, confidence_0_to_1, all_emotions_map).
    On any failure returns CALM per PROTOCOLS §4.1.
    """
    if not face_jpeg_bytes or len(face_jpeg_bytes) < 1024:
        return _DEFAULT_RESULT

    try:
        resp = _get_client().detect_faces(
            Image={"Bytes": face_jpeg_bytes},
            Attributes=["EMOTIONS"],
        )
    except Exception as exc:
        _log.warning("Rekognition DetectFaces failed: %s", exc)
        return _DEFAULT_RESULT

    faces = resp.get("FaceDetails", [])
    if not faces:
        return _DEFAULT_RESULT

    emotions = faces[0].get("Emotions", [])
    if not emotions:
        return _DEFAULT_RESULT

    all_emotions: dict[str, float] = {}
    for emo in emotions:
        label = _LABEL_MAP.get(emo.get("Type", ""))
        if label:
            all_emotions[label] = round(emo["Confidence"] / 100.0, 4)

    if not all_emotions:
        return _DEFAULT_RESULT

    dominant = max(all_emotions, key=all_emotions.__getitem__)
    return dominant, all_emotions[dominant], all_emotions
