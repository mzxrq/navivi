"""slow_move: a moving preset's clip continues as a slow move over its last
frame until the narration ends, instead of freezing."""

import subprocess

import numpy as np
import pytest

from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing import slow_move


def _clip(path, seconds=1.0):
    subprocess.run(
        [FFmpegManager.resolve_ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"testsrc2=size=320x176:rate=24:duration={seconds}", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


class TestProgress:
    def test_full_speed_from_the_join(self):
        assert slow_move._progress(0.5, 5.0) == pytest.approx(0.5)

    def test_slows_to_a_stop_at_the_end(self):
        gap = 5.0
        near_end = slow_move._progress(gap - 0.01, gap)
        at_end = slow_move._progress(gap, gap)
        assert at_end - near_end < 0.001
        assert at_end == pytest.approx(gap - 0.5)

    def test_never_goes_backwards(self):
        values = [slow_move._progress(t / 24, 3.0) for t in range(0, 73)]
        assert all(b >= a for a, b in zip(values, values[1:]))


class TestPresets:
    def test_none_and_missing_do_not_move(self):
        assert not slow_move.is_moving_preset("none")
        assert not slow_move.is_moving_preset(None)

    def test_editor_moves_do(self):
        for preset in ("pan-left", "pan-right", "pan-up", "pan-down", "zoom-in", "zoom-out"):
            assert slow_move.is_moving_preset(preset)


class TestExtend:
    def test_fills_the_gap_with_moving_frames(self, tmp_path):
        src, out = tmp_path / "in.mp4", tmp_path / "out.mp4"
        _clip(src, 1.0)
        assert slow_move.extend_with_slow_move(str(src), 3.0, "zoom-in", str(out)) == str(out)
        assert FFmpegManager.get_media_duration(str(out)) == pytest.approx(3.0, abs=0.1)
        import cv2
        cap = cv2.VideoCapture(str(out))
        frames = []
        while True:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(f.astype(np.int16))
        cap.release()
        # The tail isn't a frozen frame: consecutive tail frames differ.
        tail = frames[30:]
        assert any(np.abs(a - b).mean() > 0.05 for a, b in zip(tail, tail[1:]))

    def test_still_preset_is_left_alone(self, tmp_path):
        src = tmp_path / "in.mp4"
        _clip(src, 1.0)
        assert slow_move.extend_with_slow_move(str(src), 3.0, "none", str(tmp_path / "o.mp4")) is None

    def test_no_gap_adds_nothing(self, tmp_path):
        src = tmp_path / "in.mp4"
        _clip(src, 2.0)
        assert slow_move.extend_with_slow_move(str(src), 2.0, "zoom-in", str(tmp_path / "o.mp4")) is None


class TestRandomDrift:
    def test_directions_vary_between_clips(self):
        import random
        rng = random.Random(7)
        drifts = {tuple(round(v, 3) for v in slow_move._random_drift(rng)[:2]) for _ in range(8)}
        assert len(drifts) == 8

    def test_drift_stays_inside_the_push_in_margin_and_speed_range(self):
        import random
        rng = random.Random(3)
        base = slow_move.tuning.ATTRACTION_SLOW_MOVE_ZOOM_PER_SEC
        for _ in range(200):
            dx, dy, rate = slow_move._random_drift(rng)
            assert (dx * dx + dy * dy) ** 0.5 <= 1.0 + 1e-9
            assert 0.75 * base <= rate <= 1.25 * base
