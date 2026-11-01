"""The B-roll is streamed into the video with the same fades as when it was read whole (graphicengine/fullscreen.py)."""

import cv2
import numpy as np
import pytest

from services.mapfetcher.graphicengine import GraphicsEngine


class _Out:
    def __init__(self):
        self.frames = []

    def write(self, frame):
        self.frames.append(frame.copy())


def _whole(frames, enter, exit_, fps):
    """The old version: every frame read first, then faded in and out."""
    fade = min(int(0.5 * fps), len(frames) // 3)
    out = []
    for i, f in enumerate(frames):
        if i < fade:
            out.append(cv2.addWeighted(f, i / fade, enter, 1 - i / fade, 0))
        elif i > len(frames) - fade:
            a = (len(frames) - i) / fade
            out.append(cv2.addWeighted(f, a, exit_, 1 - a, 0))
        else:
            out.append(f)
    return out


@pytest.mark.parametrize("count", [2, 9, 40])
def test_streamed_b_roll_matches_the_whole_clip_version(tmp_path, count):
    path = str(tmp_path / "clip.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 18))
    for i in range(count):
        writer.write(np.full((18, 32, 3), i * 5, dtype=np.uint8))
    writer.release()
    cap = cv2.VideoCapture(path)
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    enter, exit_ = np.full((18, 32, 3), 250, np.uint8), np.zeros((18, 32, 3), np.uint8)

    out = _Out()
    GraphicsEngine().play_fullscreen_video(path, enter, exit_, out, fps=10)

    expected = _whole(frames, enter, exit_, 10)
    assert len(out.frames) == len(expected) == count
    assert all(np.array_equal(a, b) for a, b in zip(out.frames, expected))


def test_a_clip_without_a_frame_count_still_fades(tmp_path, monkeypatch):
    path = str(tmp_path / "clip.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 10, (32, 18))
    for _ in range(20):
        writer.write(np.full((18, 32, 3), 100, dtype=np.uint8))
    writer.release()
    real = cv2.VideoCapture

    class _NoCount:  # what OpenCV reports for a browser-recorded .webm with no duration
        def __init__(self, p):
            self._cap = real(p)

        def get(self, prop):
            return -1.0 if prop == cv2.CAP_PROP_FRAME_COUNT else self._cap.get(prop)

        def __getattr__(self, name):
            return getattr(self._cap, name)

    monkeypatch.setattr(cv2, "VideoCapture", _NoCount)
    enter = np.full((18, 32, 3), 250, np.uint8)
    out = _Out()
    GraphicsEngine().play_fullscreen_video(path, enter, np.zeros((18, 32, 3), np.uint8), out, fps=10)
    assert len(out.frames) == 20
    assert out.frames[0].mean() > 200 and out.frames[-1].mean() < 30  # faded in from enter, out to exit
