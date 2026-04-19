"""WebSocket transport for the local NIMBUS desktop client."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import numpy as np
from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.sync.client import ClientConnection, connect as ws_connect

FEATURES_PER_FRAME = 258
HAND_FEATURES = 63
POSE_FEATURES = 132
MAX_RETRIES = 5
INITIAL_BACKOFF_S = 0.5
PENDING_TTL_S = 30.0
PENDING_LIMIT = 256

logger = logging.getLogger(__name__)


class WebSocketClient:
    """Synchronous API Gateway client with reconnect and event normalization."""

    def __init__(self, url: str, session_id: str, room_id: str) -> None:
        self.url = url
        self.session_id = session_id
        self.room_id = room_id
        self._connection: ClientConnection | None = None
        self._sequence_number = 0
        self._pending_sent_at: dict[int, float] = {}
        self._last_sent_sequence: int | None = None
        self._last_server_sequence: int | None = None
        self.last_error: str | None = None

    def connect(self) -> bool:
        if self.is_connected():
            return True

        backoff_s = INITIAL_BACKOFF_S
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._connection = ws_connect(
                    self._build_connect_url(),
                    open_timeout=5,
                    close_timeout=1,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=2_000_000,
                )
                self.last_error = None
                if not self._send_control("JOIN_ROOM"):
                    raise RuntimeError("JOIN_ROOM failed")
                return True
            except Exception as exc:
                if self._connection is not None:
                    try:
                        self._connection.close()
                    except Exception:
                        logger.debug("Failed to close WebSocket after connect error", exc_info=True)
                self._connection = None
                self.last_error = f"WebSocket connect failed: {exc}"
                logger.warning("%s (attempt %s/%s)", self.last_error, attempt, MAX_RETRIES)
                if attempt == MAX_RETRIES:
                    return False
                time.sleep(backoff_s)
                backoff_s *= 2
        return False

    def is_connected(self) -> bool:
        return self._connection is not None

    def disconnect(self) -> None:
        connection = self._connection
        if connection is None:
            return

        try:
            self._send_control("LEAVE_ROOM")
        except Exception:
            logger.debug("LEAVE_ROOM best-effort send failed during disconnect", exc_info=True)
        finally:
            try:
                connection.close()
            finally:
                self._connection = None

    def send_infer(
        self,
        keypoints: np.ndarray,
        include_face_crop: bool = False,
        face_crop_b64: str | None = None,
    ) -> int | None:
        if not self.connect():
            return None

        try:
            frame = self._coerce_protocol_frame(keypoints)
        except ValueError as exc:
            self.last_error = str(exc)
            logger.warning("INFER payload rejected: %s", exc)
            return None

        self._sequence_number += 1
        sequence_number = self._sequence_number
        payload = {
            "action": "INFER",
            "sessionId": self.session_id,
            "roomId": self.room_id,
            "timestamp": self._iso_now(),
            "sequenceNumber": sequence_number,
            "payload": {
                "keypoints": self._serialize_keypoints(frame),
                "includeFaceCrop": bool(include_face_crop and face_crop_b64),
            },
        }
        if include_face_crop and face_crop_b64:
            payload["payload"]["faceCropBase64"] = face_crop_b64

        if not self._send_json(payload):
            return None

        self._last_sent_sequence = sequence_number
        self._pending_sent_at[sequence_number] = time.monotonic()
        self._prune_pending()
        return sequence_number

    def receive_event(self, timeout_ms: int = 5000) -> dict | None:
        if not self.connect():
            return self._local_error_event("WS_DISCONNECT", self.last_error or "Unable to connect")

        connection = self._connection
        if connection is None:
            return None

        try:
            raw = connection.recv(timeout=max(timeout_ms, 0) / 1000.0)
        except TimeoutError:
            self._prune_pending()
            return None
        except ConnectionClosed as exc:
            self._connection = None
            self.last_error = f"WebSocket disconnected: {exc}"
            logger.warning(self.last_error)
            if self.connect():
                return self._local_error_event("WS_RECONNECT", "Connection restored")
            return self._local_error_event("WS_DISCONNECT", self.last_error)
        except (WebSocketException, OSError, RuntimeError) as exc:
            self._connection = None
            self.last_error = f"WebSocket receive failed: {exc}"
            logger.warning(self.last_error)
            return self._local_error_event("WS_DISCONNECT", self.last_error)

        if raw is None:
            return None

        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            self.last_error = "Received invalid JSON from WebSocket"
            return self._local_error_event("WS_PROTOCOL_ERROR", self.last_error)

        return self._normalize_event(event)

    def _send_control(self, action: str) -> bool:
        return self._send_json(
            {
                "action": action,
                "sessionId": self.session_id,
                "roomId": self.room_id,
                "payload": {},
            },
            allow_reconnect=False,
        )

    def _send_json(self, payload: dict, allow_reconnect: bool = True) -> bool:
        connection = self._connection
        if connection is None:
            if not allow_reconnect or not self.connect():
                return False
            connection = self._connection
            if connection is None:
                return False

        try:
            serialized = json.dumps(payload, allow_nan=False)
        except (TypeError, ValueError) as exc:
            self.last_error = f"WebSocket payload serialization failed: {exc}"
            logger.warning(self.last_error)
            return False
        try:
            connection.send(serialized)
            self.last_error = None
            return True
        except (ConnectionClosed, WebSocketException, OSError, RuntimeError) as exc:
            self._connection = None
            self.last_error = f"WebSocket send failed: {exc}"
            logger.warning(self.last_error)
            if not allow_reconnect or not self.connect():
                return False
            retry_connection = self._connection
            if retry_connection is None:
                return False
            try:
                retry_connection.send(serialized)
                self.last_error = None
                return True
            except (ConnectionClosed, WebSocketException, OSError, RuntimeError) as retry_exc:
                self._connection = None
                self.last_error = f"WebSocket resend failed: {retry_exc}"
                logger.warning(self.last_error)
                return False

    def _normalize_event(self, event: dict) -> dict:
        event_type = event.get("type")
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}
            event["payload"] = payload

        sequence_number = event.get("sequenceNumber")
        if isinstance(sequence_number, int):
            self._last_server_sequence = sequence_number

        if event_type == "GLOSS":
            payload["tokens"] = list(payload.get("tokens") or [])
            payload["confidence"] = float(payload.get("confidence", 0.0))
            latency_ms = self._resolve_latency_ms(sequence_number, consume=False)
            if latency_ms is not None:
                payload["latencyMs"] = latency_ms
        elif event_type == "CAPTION":
            payload["text"] = str(payload.get("text") or "")
            payload["emotion"] = str(payload.get("emotion") or "CALM")
            latency_ms = payload.get("latencyMs")
            if latency_ms is None:
                latency_ms = self._resolve_latency_ms(sequence_number, consume=True)
            else:
                latency_ms = float(latency_ms)
                self._resolve_latency_ms(sequence_number, consume=True)
            if latency_ms is not None:
                payload["latencyMs"] = float(latency_ms)
        elif event_type == "EMOTION":
            payload["emotion"] = str(payload.get("emotion") or "CALM")
            payload["confidence"] = float(payload.get("confidence", 0.0))
        elif event_type == "ERROR":
            self._resolve_latency_ms(sequence_number, consume=True)
            payload["code"] = str(payload.get("code") or "UNKNOWN")
            payload["message"] = str(payload.get("message") or "")
        elif event_type == "SIGNAL":
            event["event"] = str(event.get("event") or "")

        return event

    def _resolve_latency_ms(self, sequence_number: int | None, consume: bool) -> float | None:
        key = sequence_number
        if not isinstance(key, int):
            key = self._last_server_sequence or self._last_sent_sequence
        if not isinstance(key, int):
            return None

        sent_at = self._pending_sent_at.get(key)
        if sent_at is None:
            return None

        latency_ms = (time.monotonic() - sent_at) * 1000.0
        if consume:
            self._pending_sent_at.pop(key, None)
        return latency_ms

    def _prune_pending(self) -> None:
        now = time.monotonic()
        stale = [
            sequence
            for sequence, sent_at in self._pending_sent_at.items()
            if (now - sent_at) > PENDING_TTL_S
        ]
        for sequence in stale:
            self._pending_sent_at.pop(sequence, None)

        if len(self._pending_sent_at) <= PENDING_LIMIT:
            return

        for sequence in sorted(self._pending_sent_at)[: len(self._pending_sent_at) - PENDING_LIMIT]:
            self._pending_sent_at.pop(sequence, None)

    def _build_connect_url(self) -> str:
        parsed = urlparse(self.url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["sessionId"] = self.session_id
        query["roomId"] = self.room_id
        return urlunparse(parsed._replace(query=urlencode(query)))

    @staticmethod
    def _iso_now() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @staticmethod
    def _coerce_protocol_frame(keypoints: np.ndarray) -> np.ndarray:
        array = np.asarray(keypoints, dtype=np.float32)
        if array.ndim == 1 and array.size == FEATURES_PER_FRAME:
            return array
        if array.ndim == 2 and array.shape[1] == FEATURES_PER_FRAME and len(array) > 0:
            active_rows = np.where(np.any(np.abs(array) > 1e-6, axis=1))[0]
            if active_rows.size:
                return array[int(active_rows[-1])]
            return array[-1]
        raise ValueError(f"Expected shape ({FEATURES_PER_FRAME},) or (T, {FEATURES_PER_FRAME}), got {array.shape}")

    @classmethod
    def _serialize_keypoints(cls, frame: np.ndarray) -> dict:
        left = frame[:HAND_FEATURES].reshape(21, 3)
        right = frame[HAND_FEATURES : HAND_FEATURES * 2].reshape(21, 3)
        pose = frame[HAND_FEATURES * 2 : HAND_FEATURES * 2 + POSE_FEATURES].reshape(33, 4)
        return {
            "leftHand": cls._segment_to_landmarks(left, include_visibility=False),
            "rightHand": cls._segment_to_landmarks(right, include_visibility=False),
            "pose": cls._segment_to_landmarks(pose, include_visibility=True, allow_empty=False),
        }

    @staticmethod
    def _segment_to_landmarks(
        segment: np.ndarray,
        include_visibility: bool,
        allow_empty: bool = True,
    ) -> list[dict]:
        if allow_empty and np.allclose(segment, 0.0):
            return []

        landmarks: list[dict] = []
        for row in segment:
            landmark = {
                "x": WebSocketClient._normalized_value(row[0]),
                "y": WebSocketClient._normalized_value(row[1]),
                "z": WebSocketClient._float_value(row[2]),
            }
            if include_visibility:
                landmark["visibility"] = WebSocketClient._normalized_value(row[3])
            landmarks.append(landmark)
        return landmarks

    @staticmethod
    def _normalized_value(value: float) -> float:
        numeric = WebSocketClient._float_value(value)
        return float(np.clip(numeric, 0.0, 1.0))

    @staticmethod
    def _float_value(value: float) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return 0.0
        if not np.isfinite(numeric):
            return 0.0
        return numeric

    def _local_error_event(self, code: str, message: str) -> dict:
        return {
            "type": "ERROR",
            "sessionId": self.session_id,
            "timestamp": self._iso_now(),
            "payload": {
                "code": code,
                "message": message,
            },
        }
