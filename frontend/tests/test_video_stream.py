from __future__ import annotations

import numpy as np

from capture import video_stream
from capture.video_stream import VideoStream


class _FakeCapture:
    def __init__(self) -> None:
        self.released = False
        self._frame = np.full((240, 320, 3), 7, dtype=np.uint8)

    def isOpened(self) -> bool:
        return True

    def read(self):
        return True, self._frame.copy()

    def release(self) -> None:
        self.released = True

    def set(self, *_args) -> bool:
        return True

    def get(self, prop_id: int) -> float:
        if prop_id == video_stream.cv2.CAP_PROP_FRAME_WIDTH:
            return 320.0
        if prop_id == video_stream.cv2.CAP_PROP_FRAME_HEIGHT:
            return 240.0
        return 0.0


def test_blank_frame_uses_capture_dimensions(monkeypatch) -> None:
    fake_capture = _FakeCapture()
    monkeypatch.setattr(video_stream.cv2, "VideoCapture", lambda _index: fake_capture)

    stream = VideoStream(camera_index=0)
    frame, _ = stream.read_frame()
    blank = stream.blank_frame()
    stream.release()

    assert frame.shape == (240, 320, 3)
    assert blank.shape == (240, 320, 3)
    assert np.all(blank == 0)
    assert fake_capture.released is True
