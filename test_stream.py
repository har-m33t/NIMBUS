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
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from collections import deque

import boto3
import cv2
import mediapipe as mp
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


# ---------------------------------------------------------------------------
# Keypoint extraction — 258-feature flat vector per frame
# ---------------------------------------------------------------------------

def _hand_coords(hand_landmarks) -> list[float]:
    """21 landmarks × (x, y, z) = 63 floats. Zero-padded if absent."""
    if hand_landmarks is None:
        return [0.0] * 63
    return [c for lm in hand_landmarks.landmark for c in (lm.x, lm.y, lm.z)]


def _pose_coords(pose_landmarks) -> list[float]:
    """33 landmarks × (x, y, z, visibility) = 132 floats. Zero-padded if absent."""
    if pose_landmarks is None:
        return [0.0] * 132
    return [c for lm in pose_landmarks.landmark for c in (lm.x, lm.y, lm.z, lm.visibility)]


def extract_keypoints(results) -> np.ndarray:
    """Return float32 array of shape (258,) from a MediaPipe Holistic result."""
    vec = (
        _hand_coords(results.left_hand_landmarks)
        + _hand_coords(results.right_hand_landmarks)
        + _pose_coords(results.pose_landmarks)
    )
    return np.array(vec, dtype=np.float32)


# ---------------------------------------------------------------------------
# SageMaker invocation
# ---------------------------------------------------------------------------

def _sm_runtime() -> boto3.client:
    return boto3.client("sagemaker-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))


def invoke_endpoint(
    client,
    endpoint_name: str,
    frame_buffer: np.ndarray,
) -> tuple[list[str] | None, float, str | None]:
    """
    Send frame_buffer (T, 258) to the endpoint.

    Returns:
        (tokens, confidence, error_message)
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
        return tokens, confidence, None

    except client.exceptions.ModelError as exc:
        return None, 0.0, f"Model error: {exc}"
    except Exception as exc:
        code = type(exc).__name__
        if code in RETRYABLE_CODES:
            return None, 0.0, f"Endpoint busy — retrying ({code})"
        logger.error("Unexpected SageMaker error: %s", exc, exc_info=True)
        return None, 0.0, f"Error: {exc}"


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

    # Semi-transparent dark banner at bottom
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
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_GREEN if confidence >= 0.6 else COLOR_GRAY,
                    1, cv2.LINE_AA)

    # Top-right: latency + FPS
    lat_color = _latency_color(latency_ms) if latency_ms > 0 else COLOR_GRAY
    lat_str = f"{latency_ms:.0f} ms" if latency_ms > 0 else "-- ms"
    cv2.putText(frame, lat_str, (w - 120, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, lat_color, 2, cv2.LINE_AA)
    cv2.putText(frame, f"{fps:.1f} fps", (w - 110, 54),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_GRAY, 1, cv2.LINE_AA)

    # Press Q hint
    cv2.putText(frame, "Q  quit", (12, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_GRAY, 1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(camera_index: int, buffer_frames: int, endpoint_name: str) -> None:
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open camera {camera_index}")

    sm = _sm_runtime()
    mp_holistic = mp.solutions.holistic
    mp_draw = mp.solutions.drawing_utils
    mp_styles = mp.solutions.drawing_styles

    frame_buffer: deque[np.ndarray] = deque(maxlen=buffer_frames)
    last_tokens: list[str] = []
    last_confidence = 0.0
    last_latency_ms = 0.0
    last_error: str | None = None

    next_capture = time.monotonic()
    fps_ts: deque[float] = deque(maxlen=30)

    logger.info("Streaming to endpoint: %s  |  buffer=%d frames  |  Q to quit",
                endpoint_name, buffer_frames)

    with mp_holistic.Holistic(
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    ) as holistic:
        while True:
            ret, bgr = cap.read()
            if not ret:
                logger.warning("Camera read failed — skipping frame")
                continue

            now = time.monotonic()
            fps_ts.append(now)
            display_fps = len(fps_ts) / (fps_ts[-1] - fps_ts[0] + 1e-6) if len(fps_ts) > 1 else 0.0

            # Only process + send at TARGET_FPS
            if now >= next_capture:
                next_capture = now + FRAME_INTERVAL_S

                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                results = holistic.process(rgb)
                rgb.flags.writeable = True

                kp = extract_keypoints(results)
                frame_buffer.append(kp)

                if len(frame_buffer) == buffer_frames:
                    buf_array = np.stack(list(frame_buffer))  # (T, 258)
                    t0 = time.monotonic()
                    tokens, conf, err = invoke_endpoint(sm, endpoint_name, buf_array)
                    last_latency_ms = (time.monotonic() - t0) * 1000
                    if err:
                        last_error = err
                    else:
                        last_error = None
                        last_tokens = tokens or []
                        last_confidence = conf
                    frame_buffer.clear()

                # Draw landmarks on the display frame
                mp_draw.draw_landmarks(
                    bgr, results.left_hand_landmarks,
                    mp_holistic.HAND_CONNECTIONS,
                    mp_styles.get_default_hand_landmarks_style(),
                    mp_styles.get_default_hand_connections_style(),
                )
                mp_draw.draw_landmarks(
                    bgr, results.right_hand_landmarks,
                    mp_holistic.HAND_CONNECTIONS,
                    mp_styles.get_default_hand_landmarks_style(),
                    mp_styles.get_default_hand_connections_style(),
                )
                mp_draw.draw_landmarks(
                    bgr, results.pose_landmarks,
                    mp_holistic.POSE_CONNECTIONS,
                    mp_styles.get_default_pose_landmarks_style(),
                )

            draw_overlay(bgr, last_tokens, last_confidence,
                         last_latency_ms, display_fps, last_error)
            cv2.imshow("NIMBUS — ASL Live Test  (Q to quit)", bgr)

            if cv2.waitKey(1) & 0xFF == ord("q"):
                logger.info("Q pressed — exiting")
                break

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

    # Validate SAGEMAKER_ROLE_ARN is present so the error surfaces clearly
    role_arn = os.environ.get("SAGEMAKER_ROLE_ARN")
    if not role_arn:
        raise EnvironmentError(
            "SAGEMAKER_ROLE_ARN is not set. "
            "Export it before running: export SAGEMAKER_ROLE_ARN=arn:aws:iam::<account>:role/<name>"
        )
    logger.info("Using role: %s", role_arn)

    run(
        camera_index=args.camera,
        buffer_frames=args.buffer_frames,
        endpoint_name=args.endpoint,
    )


if __name__ == "__main__":
    main()
