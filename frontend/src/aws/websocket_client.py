"""
WebSocket client for real-time communication with AWS API Gateway.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Callable

import websockets

from capture.mediapipe_extractor import Keypoints, Landmark

_log = logging.getLogger(__name__)


def _lm_dict(lm: Landmark) -> dict:
    d: dict = {"x": lm.x, "y": lm.y, "z": lm.z}
    if lm.visibility is not None:
        d["visibility"] = lm.visibility
    return d


class WebSocketClient:
    def __init__(
        self,
        endpoint_url: str,
        room_id: str,
        on_message: Callable[[dict], None] | None = None,
    ):
        self._url = endpoint_url
        self._room_id = room_id
        self._session_id = str(uuid.uuid4())
        self._seq = 0
        self._on_message = on_message
        self._ws = None

    async def connect(self) -> None:
        self._ws = await websockets.connect(self._url)
        _log.info("Connected | session=%s room=%s", self._session_id, self._room_id)

    async def disconnect(self) -> None:
        if self._ws:
            await self._ws.close()
            self._ws = None

    async def send_infer(self, keypoints: Keypoints, face_crop_b64: str | None = None) -> None:
        """
        Send one INFER frame.
        Pass face_crop_b64 on every 10th frame to trigger Rekognition emotion detection.
        includeFaceCrop is set true only when face_crop_b64 is present (face was detected).
        """
        if self._ws is None:
            raise RuntimeError("WebSocket is not connected — call connect() first")

        self._seq += 1
        include_face = face_crop_b64 is not None

        payload: dict = {
            "keypoints": {
                "leftHand": [_lm_dict(lm) for lm in keypoints.leftHand],
                "rightHand": [_lm_dict(lm) for lm in keypoints.rightHand],
                "pose": [_lm_dict(lm) for lm in keypoints.pose],
            },
            "includeFaceCrop": include_face,
        }
        if include_face:
            payload["faceCropBase64"] = face_crop_b64

        msg = {
            "action": "INFER",
            "sessionId": self._session_id,
            "roomId": self._room_id,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "sequenceNumber": self._seq,
            "payload": payload,
        }
        await self._ws.send(json.dumps(msg))
        _log.debug("INFER seq=%d includeFaceCrop=%s", self._seq, include_face)

    async def receive_loop(self) -> None:
        """Receive and dispatch backend messages until the connection closes."""
        if self._ws is None:
            return
        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                _log.warning("Non-JSON message: %s", raw[:200])
                continue
            if self._on_message:
                try:
                    self._on_message(data)
                except Exception:
                    _log.exception("on_message callback raised")

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def sequence_number(self) -> int:
        return self._seq
