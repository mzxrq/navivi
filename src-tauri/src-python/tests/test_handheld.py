"""Hand-held finish on attraction clips (services/vdoprocessing/handheld.py)."""

import subprocess

import cv2
import numpy as np

from services import tuning
from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing import handheld


def _clip(path, w=320, h=180, frames=24):
    subprocess.run(
        [FFmpegManager.resolve_ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=0x808080:s={w}x{h}:r=24", "-frames:v", str(frames), "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def test_same_seed_same_motion_and_walking_adds_footsteps():
    a = handheld.offsets(96, 24.0, False, "stop1")
    assert a == handheld.offsets(96, 24.0, False, "stop1")
    assert a != handheld.offsets(96, 24.0, False, "stop2")
    walk = handheld.offsets(96, 24.0, True, "stop1")
    bob = [w[1] - s[1] for w, s in zip(walk, a)]
    assert max(bob) - min(bob) > tuning.PARALLAX_WALK_BOB * 0.9
    assert max(abs(dx) for dx, _, _ in a) <= tuning.HANDHELD_DRIFT + 1e-9


def test_finished_clip_keeps_its_size_and_has_no_black_edges(tmp_path):
    src, dst = tmp_path / "in.mp4", tmp_path / "out.mp4"
    _clip(src)
    assert handheld.apply_handheld(str(src), str(dst), True, "stop1")
    cap = cv2.VideoCapture(str(dst))
    frames = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frames.append(frame)
    cap.release()
    assert len(frames) == 24 and frames[0].shape[:2] == (180, 320)
    corners = np.stack([f[[0, 0, -1, -1], [0, -1, 0, -1]] for f in frames])
    assert corners.min() > 100  # still the grey, never an empty border


def test_a_broken_clip_is_left_alone(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    assert not handheld.apply_handheld(str(bad), str(tmp_path / "out.mp4"), False, "x")
    assert not (tmp_path / "out.mp4").exists()
