import cv2
import numpy as np

from services import tuning
from services.vdoprocessing import sign_lock
from services.vdoprocessing.img2vdo import AttractionVideoGenerator


def _photo():
    rng = np.random.default_rng(0)
    img = (rng.random((540, 960, 3)) * 255).astype(np.uint8)
    img = cv2.GaussianBlur(img, (0, 0), 3)
    cv2.rectangle(img, (380, 200), (580, 280), (240, 240, 240), -1)
    cv2.putText(img, "SIGN", (400, 265), cv2.FONT_HERSHEY_SIMPLEX, 2, (20, 20, 20), 5)
    return img


class TestBoxes:
    def test_overlapping_lines_merge_and_only_the_largest_are_kept(self):
        merged = sign_lock._merge([(0, 0, 10, 10), (5, 5, 20, 20), (50, 50, 60, 60)])
        assert sorted(merged) == [(0, 0, 20, 20), (50, 50, 60, 60)]
        assert sign_lock._largest(merged, 1) == [(0, 0, 20, 20)]


class TestTrack:
    def test_follows_a_moving_sign_and_pastes_the_real_one(self):
        photo = _photo()
        rect = (370, 190, 590, 290)
        frames = [np.roll(photo, (0, -3 * i), axis=(0, 1)) for i in range(8)]
        quads = sign_lock.smooth_track(sign_lock.track(photo, frames, rect))
        assert all(q is not None for q in quads)
        assert abs(quads[5][0][0] - (370 - 15)) < 2
        garbled = frames[5].copy()
        garbled[205:275, 385:575] = 128
        fixed = sign_lock.paste(garbled, photo, rect, quads[5])
        got = fixed[215:270, 395:560, 0].astype(float).ravel()
        want = frames[5][215:270, 395:560, 0].astype(float).ravel()
        assert np.corrcoef(got, want)[0, 1] > 0.95

    def test_a_frame_without_the_sign_is_left_alone(self):
        photo = _photo()
        quads = sign_lock.track(photo, [np.zeros_like(photo)], (370, 190, 590, 290))
        assert quads == [None]

    def test_paste_fades_in_and_out_around_gaps(self):
        q = np.zeros((4, 2), np.float32)
        monkey = tuning.SIGN_LOCK_FADE_FRAMES
        try:
            tuning.SIGN_LOCK_FADE_FRAMES = 2
            assert sign_lock.fade_weights([q, q, q, None, q]) == [1.0, 1.0, 0.5, 0.0, 0.5]
        finally:
            tuning.SIGN_LOCK_FADE_FRAMES = monkey


class TestHook:
    def test_locks_once_and_skips_still_clips(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(sign_lock, "lock_signs", lambda clip, photo: calls.append(clip))
        clip = str(tmp_path / "raw.mp4")
        AttractionVideoGenerator._lock_signs(clip, "p.png", "panright")
        AttractionVideoGenerator._lock_signs(clip, "p.png", "panright")
        from services.vdoprocessing.camera_pan import STILL_PRESET

        AttractionVideoGenerator._lock_signs(str(tmp_path / "still.mp4"), "p.png", STILL_PRESET)
        assert calls == [clip]
