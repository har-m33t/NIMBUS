from __future__ import annotations

import time
from collections import deque

import numpy as np

import main
from main import OFFLINE_AFTER_S, current_signal, next_send_mode


def test_current_signal_uses_latency_bands() -> None:
    now = time.monotonic()

    assert current_signal(400, now)[0] == "Strong"
    assert current_signal(1000, now)[0] == "Degraded"
    assert current_signal(2000, now)[0] == "Poor"
    assert current_signal(400, now - (OFFLINE_AFTER_S + 0.1))[0] == "Offline"


def test_should_send_buffer_requires_activity() -> None:
    buffer = deque([np.zeros(258, dtype=np.float32) for _ in range(15)], maxlen=15)

    assert next_send_mode(buffer, last_activity_at=None, buffer_frames=15, frame_is_active=False) is None


def test_should_send_buffer_on_full_or_pause() -> None:
    active = np.zeros(258, dtype=np.float32)
    active[0] = 1.0
    full_buffer = deque([active.copy() for _ in range(15)], maxlen=15)
    pause_buffer = deque([active.copy()], maxlen=15)

    assert next_send_mode(
        full_buffer,
        last_activity_at=time.monotonic(),
        buffer_frames=15,
        frame_is_active=True,
    ) == "stream"
    assert next_send_mode(
        pause_buffer,
        last_activity_at=time.monotonic() - 1.0,
        buffer_frames=15,
        frame_is_active=False,
    ) == "pause"


def test_run_recovers_from_camera_read_failure(monkeypatch) -> None:
    class _FakeStream:
        def __init__(self, *args, **kwargs) -> None:
            self._calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def is_open(self) -> bool:
            return self._calls < 1

        def read_frame(self):
            self._calls += 1
            raise RuntimeError("Camera read failed for camera 0")

        def blank_frame(self):
            return np.zeros((240, 320, 3), dtype=np.uint8)

        def get_fps(self) -> float:
            return 10.0

    class _FakeExtractor:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        @staticmethod
        def zero_vector() -> np.ndarray:
            return np.zeros(258, dtype=np.float32)

        def process(self, _frame):
            raise AssertionError("process should not be called for fallback frames")

        def draw_landmarks(self, *_args) -> None:
            raise AssertionError("draw_landmarks should not be called for fallback frames")

        def extract_face_crop(self, *_args):
            return None

    class _FakeWebSocketClient:
        def __init__(self, *args, **kwargs) -> None:
            self.last_error = None

        def connect(self) -> bool:
            return True

        def receive_event(self, timeout_ms=0):
            return None

        def send_infer(self, *_args, **_kwargs):
            return None

        def disconnect(self) -> None:
            return None

    monkeypatch.setattr(main, "VideoStream", _FakeStream)
    monkeypatch.setattr(main, "MediaPipeExtractor", _FakeExtractor)
    monkeypatch.setattr(main, "WebSocketClient", _FakeWebSocketClient)
    monkeypatch.setattr(main.cv2, "imshow", lambda *_args: None)
    monkeypatch.setattr(main.cv2, "waitKey", lambda *_args: ord("q"))
    monkeypatch.setattr(main.cv2, "destroyAllWindows", lambda: None)

    main.run("wss://example.test/ws", camera_index=0, session_id="sid", room_id="room", buffer_frames=15)
