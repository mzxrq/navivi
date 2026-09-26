"""color_match: a graded clip's colours are pulled back to its photo."""

import subprocess

import cv2
import numpy as np

from services import tuning
from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing.color_match import _lab_stats, correct_frame, match_clip_to_photo


def _photo(w=320, h=176):
    rng = np.random.default_rng(0)
    base = np.zeros((h, w, 3), np.uint8)
    base[:, : w // 2] = (60, 70, 150)   # muted red wall
    base[:, w // 2 :] = (150, 150, 150)  # grey road
    noise = rng.integers(-20, 20, base.shape)
    return np.clip(base.astype(int) + noise, 0, 255).astype(np.uint8)


def _graded(img, contrast=1.4, brightness=30):
    return np.clip((img.astype(np.float32) - 128) * contrast + 128 + brightness, 0, 255).astype(np.uint8)


def test_correct_frame_restores_the_photo_stats():
    photo = _photo()
    graded = _graded(photo)
    fixed = correct_frame(graded, _lab_stats(graded), _lab_stats(photo))
    before = np.abs(_lab_stats(graded) - _lab_stats(photo)).max()
    after = np.abs(_lab_stats(fixed) - _lab_stats(photo)).max()
    assert after < before / 4


def test_strength_zero_leaves_the_frame_alone():
    photo = _photo()
    graded = _graded(photo)
    same = correct_frame(graded, _lab_stats(graded), _lab_stats(photo), strength=0.0)
    assert np.abs(same.astype(int) - graded.astype(int)).max() <= 2  # LAB round trip


def test_clip_is_rewritten_with_the_photo_colours(tmp_path):
    photo = _photo()
    photo_path = tmp_path / "photo.png"
    cv2.imwrite(str(photo_path), photo)
    clip = tmp_path / "clip.mp4"
    h, w = photo.shape[:2]
    proc = subprocess.Popen(
        [FFmpegManager.resolve_ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{w}x{h}", "-r", "24", "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(clip)],
        stdin=subprocess.PIPE,
    )
    for i in range(24):  # grading grows over the clip, like Wan's
        proc.stdin.write(_graded(photo, 1.0 + i / 40, i).tobytes())
    proc.stdin.close()
    assert proc.wait() == 0

    assert match_clip_to_photo(str(clip), str(photo_path))
    cap = cv2.VideoCapture(str(clip))
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    assert len(frames) == 24
    target = _lab_stats(photo)
    assert np.abs(_lab_stats(frames[-1]) - target)[:, 0].max() < 6  # lightness mean and spread


def test_switched_off_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(tuning, "ATTRACTION_COLOR_MATCH", False)
    assert match_clip_to_photo(str(tmp_path / "missing.mp4"), str(tmp_path / "missing.png")) is False
