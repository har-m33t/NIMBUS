"""NIMBUS local desktop client entry point."""

from __future__ import annotations

import argparse
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from uuid import uuid4

import cv2
import numpy as np

from aws.websocket_client import WebSocketClient
from capture.mediapipe_extractor import MediaPipeExtractor
from capture.video_stream import TARGET_FPS, VideoStream

DEFAULT_BUFFER_FRAMES = 15
FACE_CROP_INTERVAL = 10
PAUSE_FLUSH_S = 0.8
OFFLINE_AFTER_S = 5.0
CONFIDENCE_THRESHOLD = 0.60
ACTIVITY_EPSILON = 1e-4

COLOR_GREEN = (0, 200, 60)
COLOR_YELLOW = (0, 210, 255)
COLOR_RED = (0, 60, 220)
COLOR_GRAY = (160, 160, 160)
COLOR_WHITE = (255, 255, 255)
COLOR_BLACK = (0, 0, 0)

WINDOW_TITLE = "NIMBUS - ASL Live"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class UIState:
    gloss_tokens: list[str] = field(default_factory=list)
    confidence: float = 0.0
    emotion: str = "CALM"
    emotion_confidence: float = 0.0
    caption_text: str = ""
    audio_url: str | None = None
    latency_ms: float = 0.0
    error_message: str | None = None
    status_message: str | None = None
    status_expires_at: float = 0.0
    last_event_at: float = 0.0

    def set_status(self, message: str, ttl_s: float = 3.0) -> None:
        self.status_message = message
        self.status_expires_at = time.monotonic() + ttl_s

    def visible_status(self) -> str | None:
        if self.status_message and time.monotonic() <= self.status_expires_at:
            return self.status_message
        return None


def has_activity(keypoints: np.ndarray) -> bool:
    return bool(np.any(np.abs(keypoints) > ACTIVITY_EPSILON))


def buffer_has_activity(buffer: deque[np.ndarray]) -> bool:
    return any(has_activity(frame) for frame in buffer)


def current_signal(latency_ms: float, last_event_at: float) -> tuple[str, tuple[int, int, int]]:
    if not last_event_at or (time.monotonic() - last_event_at) > OFFLINE_AFTER_S:
        return "Offline", COLOR_GRAY
    if latency_ms < 800:
        return "Strong", COLOR_GREEN
    if latency_ms < 1500:
        return "Degraded", COLOR_YELLOW
    return "Poor", COLOR_RED


def truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)]}..."


def draw_overlay(frame: np.ndarray, state: UIState, fps: float) -> None:
    height, width = frame.shape[:2]
    banner_height = 128
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, height - banner_height), (width, height), COLOR_BLACK, -1)
    cv2.addWeighted(overlay, 0.58, frame, 0.42, 0, frame)

    gloss = " ".join(state.gloss_tokens) if state.gloss_tokens else "-"
    caption = state.caption_text or "-"
    signal_label, signal_color = current_signal(state.latency_ms, state.last_event_at)
    confidence_color = COLOR_GREEN if state.confidence >= CONFIDENCE_THRESHOLD else COLOR_GRAY
    status = state.visible_status()
    top_status = status or f"Signal {signal_label}"

    cv2.putText(frame, truncate_text(gloss, 48), (12, height - 90),
                cv2.FONT_HERSHEY_SIMPLEX, 0.82, COLOR_WHITE, 2, cv2.LINE_AA)
    cv2.putText(frame, f"conf {state.confidence * 100:.0f}%", (12, height - 62),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, confidence_color, 1, cv2.LINE_AA)
    cv2.putText(frame, f"emotion {state.emotion} ({state.emotion_confidence * 100:.0f}%)", (140, height - 62),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_WHITE, 1, cv2.LINE_AA)
    cv2.putText(frame, truncate_text(caption, 62), (12, height - 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.62, COLOR_YELLOW, 1, cv2.LINE_AA)

    latency_text = f"{state.latency_ms:.0f} ms" if state.latency_ms > 0 else "-- ms"
    cv2.putText(frame, latency_text, (width - 135, 28),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, signal_color, 2, cv2.LINE_AA)
    cv2.putText(frame, f"{fps:.1f} fps", (width - 125, 54),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, COLOR_GRAY, 1, cv2.LINE_AA)
    cv2.putText(frame, top_status, (12, 26),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, signal_color if not status else COLOR_YELLOW, 1, cv2.LINE_AA)
    cv2.putText(frame, "Q quit", (width - 82, height - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_GRAY, 1, cv2.LINE_AA)

    if state.error_message:
        cv2.putText(frame, truncate_text(state.error_message, 56), (12, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_RED, 2, cv2.LINE_AA)


def handle_event(event: dict, state: UIState) -> None:
    event_type = event.get("type")
    payload = event.get("payload") or {}

    if event_type == "GLOSS":
        state.last_event_at = time.monotonic()
        state.gloss_tokens = list(payload.get("tokens") or [])
        state.confidence = float(payload.get("confidence", 0.0))
        if "latencyMs" in payload:
            state.latency_ms = float(payload["latencyMs"])
        state.error_message = None
        return

    if event_type == "EMOTION":
        state.last_event_at = time.monotonic()
        state.emotion = str(payload.get("emotion") or "CALM")
        state.emotion_confidence = float(payload.get("confidence", 0.0))
        return

    if event_type == "CAPTION":
        state.last_event_at = time.monotonic()
        state.caption_text = str(payload.get("text") or "")
        state.emotion = str(payload.get("emotion") or state.emotion)
        state.audio_url = payload.get("audioUrl") or payload.get("ssmlUrl")
        if "latencyMs" in payload:
            state.latency_ms = float(payload["latencyMs"])
        state.error_message = None
        return

    if event_type == "SIGNAL":
        state.last_event_at = time.monotonic()
        signal_name = str(event.get("event") or "")
        if signal_name == "JOIN_ROOM":
            state.set_status("Joined room")
        elif signal_name == "LEAVE_ROOM":
            state.set_status("Left room")
        elif signal_name == "ENDPOINT_WARMING":
            state.set_status("Warming up AI model...", ttl_s=5.0)
        elif signal_name == "NEW_CAPTION":
            state.set_status("Caption delivered")
        return

    if event_type == "ERROR":
        code = str(payload.get("code") or "ERROR")
        message = str(payload.get("message") or code)
        if not code.startswith("WS_"):
            state.last_event_at = time.monotonic()
        if code == "WS_RECONNECT":
            state.set_status(message)
            state.error_message = None
        elif code == "WS_DISCONNECT":
            state.set_status("Reconnecting...", ttl_s=5.0)
            state.error_message = message
        else:
            state.error_message = f"{code}: {message}"


def drain_events(ws_client: WebSocketClient, state: UIState) -> None:
    for _ in range(10):
        event = ws_client.receive_event(timeout_ms=1)
        if event is None:
            break
        handle_event(event, state)


def next_send_mode(
    keypoint_buffer: deque[np.ndarray],
    last_activity_at: float | None,
    buffer_frames: int,
    frame_is_active: bool,
) -> str | None:
    if not keypoint_buffer or not buffer_has_activity(keypoint_buffer):
        return None

    if len(keypoint_buffer) >= buffer_frames and buffer_has_activity(keypoint_buffer):
        return "stream"

    if last_activity_at is None or frame_is_active:
        return None

    if (time.monotonic() - last_activity_at) >= PAUSE_FLUSH_S:
        return "pause"
    return None


def run(
    server_url: str,
    camera_index: int,
    session_id: str,
    room_id: str,
    buffer_frames: int,
) -> None:
    ui_state = UIState(status_message="Connecting...", status_expires_at=time.monotonic() + 3.0)
    keypoint_buffer: deque[np.ndarray] = deque(maxlen=max(1, buffer_frames))
    last_activity_at: float | None = None
    send_count = 0

    with VideoStream(camera_index=camera_index, target_fps=TARGET_FPS) as stream, \
            MediaPipeExtractor() as extractor:
        ws_client = WebSocketClient(server_url, session_id=session_id, room_id=room_id)
        if not ws_client.connect():
            raise RuntimeError(ws_client.last_error or "Unable to connect to WebSocket server")
        ui_state.set_status("Connected")

        # Cold-start grace window: wait up to 3s for the JOIN_ROOM ack so the
        # initial SIGNAL isn't dropped by the 1ms timeout in drain_events().
        initial_event = ws_client.receive_event(timeout_ms=3000)
        if initial_event is not None:
            handle_event(initial_event, ui_state)

        logger.info(
            "Starting client session=%s room=%s camera=%s buffer=%s",
            session_id,
            room_id,
            camera_index,
            buffer_frames,
        )

        try:
            while stream.is_open():
                try:
                    frame, _timestamp_ns = stream.read_frame()
                except RuntimeError as exc:
                    logger.warning("Camera read failed; using blank frame: %s", exc)
                    frame = stream.blank_frame()
                    keypoints = extractor.zero_vector()
                    results = None
                    ui_state.error_message = str(exc)
                    ui_state.set_status("Camera signal lost; retrying...", ttl_s=2.0)
                else:
                    if ui_state.error_message and ui_state.error_message.startswith("Camera read failed"):
                        ui_state.error_message = None
                        ui_state.set_status("Camera recovered", ttl_s=1.5)
                    keypoints, results = extractor.process(frame)
                    extractor.draw_landmarks(frame, results)

                keypoint_buffer.append(keypoints)
                frame_is_active = has_activity(keypoints)

                if frame_is_active:
                    last_activity_at = time.monotonic()

                send_mode = next_send_mode(
                    keypoint_buffer,
                    last_activity_at,
                    buffer_frames,
                    frame_is_active=frame_is_active,
                )
                if send_mode:
                    send_count += 1
                    include_face_crop = (send_count % FACE_CROP_INTERVAL) == 0
                    face_crop_b64 = (
                        extractor.extract_face_crop(frame, results)
                        if include_face_crop
                        else None
                    )
                    buffer_array = np.stack(list(keypoint_buffer))
                    sequence_number = ws_client.send_infer(
                        buffer_array,
                        include_face_crop=include_face_crop,
                        face_crop_b64=face_crop_b64,
                    )
                    if sequence_number is None:
                        ui_state.error_message = ws_client.last_error
                    elif send_mode == "pause":
                        ui_state.set_status("Sentence boundary detected", ttl_s=1.5)
                    if send_mode == "pause":
                        keypoint_buffer.clear()
                        last_activity_at = None

                drain_events(ws_client, ui_state)
                draw_overlay(frame, ui_state, stream.get_fps())
                cv2.imshow(WINDOW_TITLE, frame)

                if cv2.waitKey(1) & 0xFF == ord("q"):
                    logger.info("Quit requested from UI")
                    break
        finally:
            ws_client.disconnect()
            cv2.destroyAllWindows()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local NIMBUS ASL client")
    parser.add_argument("--server-url", required=True, help="API Gateway WebSocket URL")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV camera index")
    parser.add_argument("--session-id", default=str(uuid4()), help="Session UUIDv4")
    parser.add_argument("--room-id", default="default", help="Room identifier")
    parser.add_argument(
        "--buffer-frames",
        type=int,
        default=DEFAULT_BUFFER_FRAMES,
        help=f"Rolling keypoint buffer size before a send (default {DEFAULT_BUFFER_FRAMES})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        run(
            server_url=args.server_url,
            camera_index=args.camera,
            session_id=args.session_id,
            room_id=args.room_id,
            buffer_frames=args.buffer_frames,
        )
    except KeyboardInterrupt:
        logger.info("Interrupted")
    except RuntimeError as exc:
        logger.error("Startup failed: %s", exc)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
