"""
Entry point for the ASL local desktop application.
Initializes the capture stream, handles UI/state, and connects to AWS WebSocket.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading

from dotenv import load_dotenv

from capture.mediapipe_extractor import ExtractResult, MediaPipeExtractor
from capture.video_stream import VideoStream
from aws.websocket_client import WebSocketClient

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
_log = logging.getLogger("nimbus.main")

_FACE_CROP_INTERVAL = 10   # must match backend FACE_CROP_INTERVAL
_WS_URL = os.environ.get("NIMBUS_WS_URL", "")
_ROOM_ID = os.environ.get("NIMBUS_ROOM_ID", "room-default")


def _on_backend_message(msg: dict) -> None:
    msg_type = msg.get("type", "UNKNOWN")
    if msg_type == "GLOSS":
        tokens = msg.get("payload", {}).get("tokens", [])
        _log.info("[GLOSS] %s", " ".join(tokens))
    elif msg_type == "EMOTION":
        emo = msg.get("payload", {}).get("emotion", "?")
        conf = msg.get("payload", {}).get("confidence", 0)
        _log.info("[EMOTION] %s (%.0f%%)", emo, conf * 100)
    elif msg_type == "CAPTION":
        text = msg.get("payload", {}).get("text", "")
        _log.info("[CAPTION] %s", text)
    elif msg_type == "ERROR":
        code = msg.get("payload", {}).get("code", "")
        _log.warning("[ERROR] %s", code)
    elif msg_type == "SIGNAL":
        _log.debug("[SIGNAL] %s", msg.get("event"))


async def _capture_and_send(ws_client: WebSocketClient) -> None:
    """
    Run MediaPipe + frame capture in a background thread (blocking ops),
    bridge results to the async WebSocket sender via an asyncio.Queue.
    Face crops (base64 JPEG, ≤640×480) are extracted every 10th frame and
    included in the INFER payload to trigger Rekognition emotion detection.
    """
    queue: asyncio.Queue[ExtractResult] = asyncio.Queue(maxsize=5)
    loop = asyncio.get_running_loop()
    stop_flag = threading.Event()

    def _worker() -> None:
        frame_num = 0
        with VideoStream() as vs, MediaPipeExtractor() as mp_ext:
            for frame_bgr in vs.frames_at_10fps():
                if stop_flag.is_set():
                    break
                frame_num += 1
                include_face = (frame_num % _FACE_CROP_INTERVAL == 0)
                result = mp_ext.extract(frame_bgr, include_face_crop=include_face)
                try:
                    asyncio.run_coroutine_threadsafe(
                        queue.put(result), loop
                    ).result(timeout=2.0)
                except Exception:
                    _log.warning("Queue put timed out — dropping frame %d", frame_num)

    thread = threading.Thread(target=_worker, daemon=True, name="capture-worker")
    thread.start()

    try:
        while thread.is_alive() or not queue.empty():
            try:
                result = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            await ws_client.send_infer(
                result.keypoints,
                face_crop_b64=result.face_crop_b64,
            )
    finally:
        stop_flag.set()


async def _main_async() -> None:
    if not _WS_URL:
        _log.error("Set NIMBUS_WS_URL to the API Gateway WebSocket endpoint")
        sys.exit(1)

    client = WebSocketClient(
        endpoint_url=_WS_URL,
        room_id=_ROOM_ID,
        on_message=_on_backend_message,
    )

    await client.connect()
    _log.info("Session: %s", client.session_id)

    try:
        await asyncio.gather(
            _capture_and_send(client),
            client.receive_loop(),
        )
    finally:
        await client.disconnect()


def main():
    asyncio.run(_main_async())


if __name__ == "__main__":
    main()
