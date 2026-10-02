"""Multi-shot attraction clips (2026-10-02): clip_qc flags invented content
but not camera motion, parallax_generator moves the real photo with depth,
shot_builder cuts each Wan shot where it goes bad, settles it before a hard
cut and fills the rest with parallax."""

import cv2
import numpy as np
import pytest

from services import tuning
from services.vdoprocessing import clip_qc, parallax_generator, shot_builder

FPS = float(tuning.COMFYUI_FPS)


def _photo(w=1280, h=720, seed=1):
    rng = np.random.default_rng(seed)
    img = cv2.resize(rng.integers(0, 255, (h // 16, w // 16, 3), dtype=np.uint8), (w, h), interpolation=cv2.INTER_CUBIC)
    for _ in range(60):
        x, y = int(rng.integers(0, w - 60)), int(rng.integers(0, h - 60))
        cv2.rectangle(img, (x, y), (x + 50, y + 30), tuple(int(c) for c in rng.integers(0, 255, 3)), -1)
    return img


def _zoom(img, s):
    h, w = img.shape[:2]
    m = np.float32([[s, 0, w / 2 * (1 - s)], [0, s, h / 2 * (1 - s)]])
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC)


class TestClipQC:
    def test_camera_motion_passes(self):
        photo = _photo()
        frames = [_zoom(photo, 1 + 0.1 * i / 20) for i in range(21)]
        assert clip_qc.first_bad_frame(frames, photo) is None

    def test_invented_object_is_flagged_where_it_appears(self):
        photo = _photo()
        frames = [_zoom(photo, 1 + 0.05 * i / 20) for i in range(21)]
        for f in frames[8:]:
            cv2.circle(f, (900, 250), 150, (255, 0, 255), -1)  # a big new sign
        assert clip_qc.first_bad_frame(frames, photo) == 8

    def test_a_different_scene_is_flagged(self):
        photo = _photo()
        assert clip_qc.first_bad_frame([photo, _photo(seed=7)], photo) == 1


class TestParallax:
    @pytest.fixture
    def clip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(parallax_generator, "_lama", False)  # no 200 MB model in tests
        path = tmp_path / "photo.png"
        cv2.imwrite(str(path), _photo(1600, 900))

        def make(preset, flat=False):
            out = str(tmp_path / f"{preset}.mp4")
            # left far (0) to right near (1), or one depth everywhere
            depth = lambda img: (
                np.full(img.shape[:2], 0.5, np.float32) if flat
                else np.tile(np.linspace(0, 1, img.shape[1], dtype=np.float32), (img.shape[0], 1))
            )
            parallax_generator.generate_parallax_clip(str(path), out, 1.0, preset, depth_fn=depth)
            return clip_qc.read_frames(out)
        return make

    @staticmethod
    def _shift(a, b, x0, x1):
        g = lambda f: np.float32(cv2.cvtColor(f[300:780, x0:x1], cv2.COLOR_BGR2GRAY))
        return cv2.phaseCorrelate(g(a), g(b))[0][0]

    def test_length_and_size(self, clip):
        frames = clip("panright")
        assert len(frames) == round(FPS)
        assert frames[0].shape[:2] == (1080, 1920)

    def test_pan_right_moves_content_left_near_more_than_far(self, clip):
        frames = clip("panright")
        far = self._shift(frames[0], frames[-1], 100, 700)
        near = self._shift(frames[0], frames[-1], 1220, 1820)
        assert far < -5 and near < far

    def test_zoom_in_grows_the_picture(self, tmp_path, monkeypatch):
        monkeypatch.setattr(parallax_generator, "_lama", False)
        photo = np.full((900, 1600, 3), 128, np.uint8)
        cv2.rectangle(photo, (330, 420), (370, 480), (0, 0, 255), -1)    # red, left of centre
        cv2.rectangle(photo, (1230, 420), (1270, 480), (0, 255, 0), -1)  # green, right of centre
        path = tmp_path / "markers.png"
        cv2.imwrite(str(path), photo)
        out = str(tmp_path / "zoom.mp4")
        flat = lambda img: np.full(img.shape[:2], 0.5, np.float32)
        parallax_generator.generate_parallax_clip(str(path), out, 1.0, "zoomin", depth_fn=flat)
        frames = clip_qc.read_frames(out)

        def x_of(frame, channel):
            others = [c for c in range(3) if c != channel]
            mask = (frame[..., channel] > 180) & (frame[..., others[0]] < 90) & (frame[..., others[1]] < 90)
            return np.nonzero(mask)[1].mean()

        assert x_of(frames[-1], 2) < x_of(frames[0], 2)  # left marker moves left
        assert x_of(frames[-1], 1) > x_of(frames[0], 1)  # right marker moves right


class TestSettle:
    def test_eases_to_a_stop_then_holds(self):
        frames = [np.full((4, 4, 3), i * 10, np.uint8) for i in range(24)]
        out = shot_builder.settle(frames, FPS)
        src = round(tuning.ATTRACTION_SHOT_SETTLE_SECONDS * FPS)
        hold = round(tuning.ATTRACTION_SHOT_HOLD_SECONDS * FPS)
        assert len(out) == 24 + src - 1 + hold
        values = [int(f[0, 0, 0]) for f in out]
        assert values == sorted(values)
        assert values[-hold - 1:] == [230] * (hold + 1)
        steps = np.diff(values[24 - src - 1: 24 + src - 1])
        assert steps[-1] < steps[0]

    def test_fits_the_time_left(self):
        frames = [np.zeros((4, 4, 3), np.uint8)] * 60
        assert len(shot_builder.settle(frames, FPS, max_frames=40)) <= 40


def test_shot_moves_start_with_the_preset_and_skip_repeats():
    assert shot_builder.shot_moves("Zoom-In") == ["zoomin", "walkin", "dollyback"]
    assert shot_builder.shot_moves("walk-in")[:2] == ["walkin", "dollyback"]


class TestBuildShots:
    def _run(self, tmp_path, monkeypatch, bad_frames, duration):
        photo = tmp_path / "photo.png"
        cv2.imwrite(str(photo), _photo(640, 360))
        calls, fills = [], []

        def wan(photo_path, path, move, seconds):
            calls.append(move)
            shot_builder._write([np.full((352, 640, 3), 100, np.uint8)] * 89, FPS, path)

        def parallax(photo_path, path, seconds, preset):
            fills.append(seconds)
            shot_builder._write([np.full((1080, 1920, 3), 50, np.uint8)] * max(1, round(seconds * FPS)), FPS, path)
            return path

        verdicts = iter(bad_frames)
        monkeypatch.setattr(clip_qc, "first_bad_frame", lambda *a, **k: next(verdicts))
        out = str(tmp_path / "out.mp4")
        shot_builder.build_shots(str(photo), out, duration, "zoomin", wan_shot=wan, parallax=parallax)
        return calls, fills, len(clip_qc.read_frames(out))

    def test_three_wan_shots_then_parallax_fill(self, tmp_path, monkeypatch):
        calls, fills, n = self._run(tmp_path, monkeypatch, [40, 40, 40], 12.0)
        assert calls == ["zoomin", "walkin", "dollyback"]
        assert len(fills) == 1 and fills[0] > 3
        assert abs(n - 12.0 * FPS) <= 1

    def test_too_short_shots_are_dropped(self, tmp_path, monkeypatch):
        calls, fills, n = self._run(tmp_path, monkeypatch, [10, 10, 10], 6.0)
        assert len(calls) == 3
        assert fills == [pytest.approx(6.0, abs=0.05)]
        assert abs(n - 6.0 * FPS) <= 1

    def test_short_narration_needs_no_fill(self, tmp_path, monkeypatch):
        calls, fills, n = self._run(tmp_path, monkeypatch, [None], 2.0)
        assert calls == ["zoomin"] and fills == []
        assert abs(n - 2.0 * FPS) <= 1

    def test_wan_failure_falls_back_to_parallax(self, tmp_path, monkeypatch):
        photo = tmp_path / "photo.png"
        cv2.imwrite(str(photo), _photo(640, 360))

        def wan(*a):
            raise RuntimeError("server down")

        fills = []

        def parallax(photo_path, path, seconds, preset):
            fills.append(seconds)
            shot_builder._write([np.zeros((1080, 1920, 3), np.uint8)] * round(seconds * FPS), FPS, path)
            return path

        shot_builder.build_shots(str(photo), str(tmp_path / "o.mp4"), 3.0, "panright", wan_shot=wan, parallax=parallax)
        assert fills == [pytest.approx(3.0, abs=0.05)]
