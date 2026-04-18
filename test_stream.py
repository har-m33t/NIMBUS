"""
NIMBUS — Real-time ASL inference test stream.

Captures webcam at 10 FPS, extracts MediaPipe keypoints (258 features/frame),
accumulates a rolling buffer, invokes nimbus-prod-asl-endpoint, and overlays
the predicted gloss token + confidence on the live video window.

Usage:
    python test_stream.py
    python test_stream.py --camera 1 --buffer-frames 15 --endpoint nimbus-prod-asl-endpoint

Press Q to quit.
Requires: SAGEMAKER_ROLE_ARN in environment (for assumed-role credential chain).

Model files (~30 MB total) are downloaded automatically on first run to .mediapipe_models/.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
import urllib.request
from collections import deque
from pathlib import Path
from typing import Any

import boto3
import cv2
import mediapipe as mp
from mediapipe.tasks import python as _mp_tasks
from mediapipe.tasks.python import vision as _mp_vision
from mediapipe.tasks.python.core.base_options import BaseOptions
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ENDPOINT_NAME = "nimbus-prod-asl-endpoint"
TARGET_FPS = 10
FRAME_INTERVAL_S = 1.0 / TARGET_FPS
FEATURES_PER_FRAME = 258          # 63 left + 63 right + 132 pose
DEFAULT_BUFFER_FRAMES = 15        # flush after this many frames

# Signal quality thresholds (ms) — from PROTOCOLS.md
LATENCY_GREEN  = 800
LATENCY_YELLOW = 1500
CONFIDENCE_THRESHOLD = 0.60

# Overlay colours (BGR)
COLOR_GREEN  = (0, 200, 60)
COLOR_YELLOW = (0, 210, 255)
COLOR_RED    = (0, 60, 220)
COLOR_GRAY   = (160, 160, 160)
COLOR_WHITE  = (255, 255, 255)
COLOR_BLACK  = (0, 0, 0)

# Transient error messages to surface in the overlay instead of crashing
RETRYABLE_CODES = {
    "ModelNotReadyException",
    "ServiceUnavailableException",
    "ThrottlingException",
    "ModelError",
}

# Permanent misconfiguration — logged once, not retried with traceback spam
TERMINAL_CODES = {
    "ValidationError",           # endpoint not found / bad request
    "AccessDeniedException",     # IAM
    "ResourceNotFoundException",
}
_logged_terminal: set[str] = set()

# ---------------------------------------------------------------------------
# MediaPipe Tasks model bootstrap
# ---------------------------------------------------------------------------

_MODEL_DIR = Path(__file__).parent / ".mediapipe_models"
_HAND_MODEL = _MODEL_DIR / "hand_landmarker.task"
_POSE_MODEL = _MODEL_DIR / "pose_landmarker_full.task"
_HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)
_POSE_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "pose_landmarker/pose_landmarker_full/float16/1/pose_landmarker_full.task"
)


def _ensure_models() -> None:
    _MODEL_DIR.mkdir(exist_ok=True)
    for path, url in ((_HAND_MODEL, _HAND_MODEL_URL), (_POSE_MODEL, _POSE_MODEL_URL)):
        if not path.exists():
            logger.info("Downloading %s (~30 MB) ...", path.name)
            urllib.request.urlretrieve(url, path)
            logger.info("Saved %s", path)


# ---------------------------------------------------------------------------
# Landmark drawing — manual OpenCV (mp.solutions.drawing_utils removed in 0.10.18+)
# ---------------------------------------------------------------------------

_HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),
    (0, 5), (5, 6), (6, 7), (7, 8),
    (0, 9), (9, 10), (10, 11), (11, 12),
    (0, 13), (13, 14), (14, 15), (15, 16),
    (0, 17), (17, 18), (18, 19), (19, 20),
    (5, 9), (9, 13), (13, 17),
]

_POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),
    (11, 23), (12, 24), (23, 24),
]


def _draw_landmarks(frame: np.ndarray, hand_result, pose_result) -> None:
    h, w = frame.shape[:2]

    if hand_result and hand_result.hand_landmarks:
        for lms in hand_result.hand_landmarks:
            pts = [(int(lm.x * w), int(lm.y * h)) for lm in lms]
            for a, b in _HAND_CONNECTIONS:
                cv2.line(frame, pts[a], pts[b], COLOR_GREEN, 1, cv2.LINE_AA)
            for cx, cy in pts:
                cv2.circle(frame, (cx, cy), 4, COLOR_GREEN, -1)

    if pose_result and pose_result.pose_landmarks:
        lms = pose_result.pose_landmarks[0]
        pts = [(int(lm.x * w), int(lm.y * h)) for lm in lms]
        for a, b in _POSE_CONNECTIONS:
            if a < len(pts) and b < len(pts):
                cv2.line(frame, pts[a], pts[b], COLOR_YELLOW, 1, cv2.LINE_AA)
        for cx, cy in pts[11:25]:
            cv2.circle(frame, (cx, cy), 3, COLOR_YELLOW, -1)


# ---------------------------------------------------------------------------
# Keypoint extraction — 258-feature flat vector per frame
# ---------------------------------------------------------------------------

def _hand_coords_from_result(hand_result, label: str) -> list[float]:
    if not hand_result or not hand_result.hand_landmarks or not hand_result.handedness:
        return [0.0] * 63
    for i, lms in enumerate(hand_result.hand_landmarks):
        if i >= len(hand_result.handedness):
            continue
        item = hand_result.handedness[i]
        if hasattr(item, "category_name"):
            cat = item.category_name
        elif isinstance(item, list) and item:
            cat = item[0].category_name
        else:
            continue
        if cat == label:
            return [c for lm in lms for c in (lm.x, lm.y, lm.z)]
    return [0.0] * 63


def extract_keypoints(hand_result, pose_result) -> np.ndarray:
    """Return float32 array of shape (258,) from Tasks API landmarker results."""
    left  = _hand_coords_from_result(hand_result, "Left")
    right = _hand_coords_from_result(hand_result, "Right")

    pose = [0.0] * 132
    if pose_result and pose_result.pose_landmarks and len(pose_result.pose_landmarks) > 0:
        lms = pose_result.pose_landmarks[0]
        pose_data: list[float] = []
        for lm in lms:
            pose_data.extend([lm.x, lm.y, lm.z,
                               lm.visibility if hasattr(lm, "visibility") else 0.0])
        pose = pose_data[:132]

    return np.array(left + right + pose, dtype=np.float32)


# ---------------------------------------------------------------------------
# SageMaker invocation
# ---------------------------------------------------------------------------

def _sm_runtime() -> Any:
    return boto3.client("sagemaker-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def invoke_endpoint(
    client,
    endpoint_name: str,
    frame_buffer: np.ndarray,
) -> tuple[list[str] | None, float, str | None, float]:
    """
    Send frame_buffer (T, 258) to the endpoint.

    Returns:
        (tokens, confidence, error_message, latency_ms)
        tokens is None and error_message is set on transient failures.
    """
    flat = frame_buffer.flatten().tolist()
    body = json.dumps({"instances": [{"keypoints": flat}]})

    t0 = time.monotonic()
    try:
        resp = client.invoke_endpoint(
            EndpointName=endpoint_name,
            ContentType="application/json",
            Accept="application/json",
            Body=body,
        )
        latency_ms = (time.monotonic() - t0) * 1000
        result = json.loads(resp["Body"].read())
        tokens = result.get("tokens") or []
        confidence = float(result.get("confidence", 0.0))
        return tokens, confidence, None, latency_ms

    except client.exceptions.ModelError as exc:
        return None, 0.0, f"Model error: {exc}", 0.0
    except Exception as exc:
        code = type(exc).__name__
        if code in RETRYABLE_CODES:
            return None, 0.0, f"Endpoint busy — retrying ({code})", 0.0
        if code in TERMINAL_CODES:
            if code not in _logged_terminal:
                _logged_terminal.add(code)
                logger.warning("SageMaker %s (suppressing further tracebacks): %s", code, exc)
            return None, 0.0, f"{code}: endpoint unavailable", 0.0
        if code not in _logged_terminal:
            _logged_terminal.add(code)
            logger.error("Unexpected SageMaker error: %s", exc, exc_info=True)
        return None, 0.0, f"Error: {code}", 0.0


# ---------------------------------------------------------------------------
# Overlay rendering
# ---------------------------------------------------------------------------

def _latency_color(latency_ms: float) -> tuple[int, int, int]:
    if latency_ms < LATENCY_GREEN:
        return COLOR_GREEN
    if latency_ms < LATENCY_YELLOW:
        return COLOR_YELLOW
    return COLOR_RED


def draw_overlay(
    frame: np.ndarray,
    tokens: list[str] | None,
    confidence: float,
    latency_ms: float,
    fps: float,
    error_msg: str | None,
) -> None:
    """Mutates frame in-place with prediction overlay."""
    h, w = frame.shape[:2]

    banner_h = 80
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - banner_h), (w, h), COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

    if error_msg:
        cv2.putText(frame, error_msg, (12, h - banner_h + 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, COLOR_YELLOW, 2, cv2.LINE_AA)
    else:
        gloss = " ".join(tokens) if tokens else "—"
        conf_pct = f"{confidence * 100:.0f}%"
        cv2.putText(frame, gloss, (12, h - banner_h + 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, COLOR_WHITE, 2, cv2.LINE_AA)
        cv2.putText(frame, f"conf {conf_pct}", (12, h - banner_h + 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                    COLOR_GREEN if confidence >= CONFIDENCE_THRESHOLD else COLOR_GRAY,
                    1, cv2.LINE_AA)

    lat_color = _latency_color(latency_ms) if latency_ms > 0 else COLOR_GRAY
    lat_str = f"{latency_ms:.0f} ms" if latency_ms > 0 else "-- ms"
    cv2.putText(frame, lat_str, (w - 120, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, lat_color, 2, cv2.LINE_AA)
    cv2.putText(frame, f"{fps:.1f} fps", (w - 110, 54),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_GRAY, 1, cv2.LINE_AA)
    cv2.putText(frame, "Q  quit", (12, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_GRAY, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(camera_index: int, buffer_frames: int, endpoint_name: str) -> None:
    _ensure_models()

    hand_opts = _mp_vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(_HAND_MODEL)),
        running_mode=_mp_vision.RunningMode.IMAGE,
        num_hands=2,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )
    pose_opts = _mp_vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(_POSE_MODEL)),
        running_mode=_mp_vision.RunningMode.IMAGE,
        min_pose_detection_confidence=0.5,
        min_pose_presence_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera {camera_index}")

    try:
        sm = _sm_runtime()
        frame_buffer: deque[np.ndarray] = deque(maxlen=buffer_frames)
        last_tokens: list[str] = []
        last_confidence = 0.0
        last_latency_ms = 0.0
        last_error: str | None = None

        next_capture = time.monotonic()
        fps_ts: deque[float] = deque(maxlen=30)

        logger.info("Streaming to endpoint: %s  |  buffer=%d frames  |  Q to quit",
                    endpoint_name, buffer_frames)

        with (_mp_vision.HandLandmarker.create_from_options(hand_opts) as hand_lmk,
              _mp_vision.PoseLandmarker.create_from_options(pose_opts) as pose_lmk):
            while True:
                ret, bgr = cap.read()
                if not ret:
                    logger.warning("Camera read failed — skipping frame")
                    continue

                now = time.monotonic()
                fps_ts.append(now)
                display_fps = (len(fps_ts) / (fps_ts[-1] - fps_ts[0])
                               if len(fps_ts) > 1 else 0.0)

                if now >= next_capture:
                    next_capture = now + FRAME_INTERVAL_S

                    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

                    hand_result = hand_lmk.detect(mp_image)
                    pose_result = pose_lmk.detect(mp_image)

                    kp = extract_keypoints(hand_result, pose_result)
                    frame_buffer.append(kp)

                    if len(frame_buffer) == buffer_frames:
                        buf_array = np.stack(list(frame_buffer))  # (T, 258)
                        tokens, conf, err, last_latency_ms = invoke_endpoint(sm, endpoint_name, buf_array)
                        if err:
                            last_error = err
                        else:
                            last_error = None
                            last_tokens = tokens or []
                            last_confidence = conf
                        frame_buffer.clear()

                    _draw_landmarks(bgr, hand_result, pose_result)

                draw_overlay(bgr, last_tokens, last_confidence,
                             last_latency_ms, display_fps, last_error)
                cv2.imshow("NIMBUS — ASL Live Test  (Q to quit)", bgr)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    logger.info("Q pressed — exiting")
                    break
    finally:
        cap.release()
        cv2.destroyAllWindows()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="NIMBUS real-time ASL stream tester")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index (default 0)")
    parser.add_argument("--buffer-frames", type=int, default=DEFAULT_BUFFER_FRAMES,
                        help=f"Frames to accumulate before each inference call (default {DEFAULT_BUFFER_FRAMES})")
    parser.add_argument("--endpoint", default=ENDPOINT_NAME,
                        help=f"SageMaker endpoint name (default {ENDPOINT_NAME})")
    args = parser.parse_args()

    role_arn = os.environ.get("SAGEMAKER_ROLE_ARN")
    if not role_arn:
        raise EnvironmentError(
            "SAGEMAKER_ROLE_ARN is not set. "
            "Export it before running: export SAGEMAKER_ROLE_ARN=arn:aws:iam::<account>:role/<name>"
        )
    logger.info("Using role: %s", role_arn)

    try:
        run(
            camera_index=args.camera,
            buffer_frames=args.buffer_frames,
            endpoint_name=args.endpoint,
        )
    except RuntimeError as exc:
        logger.error("Startup failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
