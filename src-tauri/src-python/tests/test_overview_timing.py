import numpy as np

from services.vdoprocessing.spatial_renderer.overview_timing import (
    MIN_SECONDS_AFTER_LAST_CUE,
    animation_frames,
    intro_frame_count,
    stop_targets,
    warp_controls,
    warp_path,
)

FPS = 30


def test_intro_frame_count_matches_the_writes():
    # clean 45 + bounce 9 + remaining (90-45-9=36) + bounce 9
    assert intro_frame_count(3.0, 1.5, 9, FPS) == 45 + 9 + 36 + 9


def test_walk_ends_at_end_cue():
    assert animation_frames({"end": 50.0}, 100, FPS) == 50 * FPS - 100


def test_walk_reaches_the_last_cued_stop():
    n = animation_frames({"1": 10.0, "2": 20.0}, 100, FPS)
    assert n == round((20.0 + MIN_SECONDS_AFTER_LAST_CUE) * FPS) - 100


def test_no_cues_no_walk_length():
    assert animation_frames({}, 100, FPS) == 0


def test_stops_land_on_their_cues_and_the_rest_keep_their_place():
    natural = {1: 100, 2: 200, 3: 300}
    targets = stop_targets(natural, {"1": 10.0, "3": 20.0}, 90, FPS, 900)
    assert targets[1] == 10 * FPS - 90
    assert targets[3] == 20 * FPS - 90
    assert targets[1] < targets[2] < targets[3]


def test_no_cues_no_retiming():
    assert stop_targets({1: 100}, {}, 90, FPS, 900) == {}


def test_targets_stay_strictly_increasing_and_inside_the_walk():
    targets = stop_targets({1: 100, 2: 200}, {"1": 1000.0, "2": 0.5}, 0, FPS, 300)
    assert 0 < targets[1] < targets[2] <= 299


def test_warp_puts_the_traveler_at_the_stop_on_time():
    n = 300
    path = np.stack([np.arange(n, dtype=float), np.zeros(n)], axis=1)
    natural = {1: 100}
    xs, ys = warp_controls(natural, {1: 200}, n)
    warped, cum = warp_path(path, np.arange(n, dtype=float), xs, ys)
    assert abs(warped[200, 0] - 100) < 1e-6  # reaches natural frame 100 at frame 200
    assert warped[0, 0] == 0 and abs(warped[-1, 0] - (n - 1)) < 1e-6
    assert np.all(np.diff(warped[:, 0]) >= 0)
    assert abs(cum[200] - 100) < 1e-6


def test_a_long_leg_is_capped_and_short_ones_are_kept():
    from services.vdoprocessing.spatial_renderer.overview_timing import cap_segments

    n = 1000
    path = np.stack([np.arange(n, dtype=float), np.zeros(n)], axis=1)
    # legs: 0-100 (short), 100-900 (long), 900-999 (short); cap 300 frames
    out, cum = cap_segments(path, np.arange(n, dtype=float), [0, 100, 900, 999], 300)
    assert len(out) == 100 + 300 + 99 + 1
    assert out[100, 0] == 100 and abs(out[400, 0] - 900) < 1e-6
    assert abs(out[-1, 0] - 999) < 1e-6


def test_short_legs_are_left_alone():
    from services.vdoprocessing.spatial_renderer.overview_timing import cap_segments

    path = np.zeros((500, 2))
    out, _ = cap_segments(path, None, [0, 200, 499], 300)
    assert out is path


def test_an_overview_card_is_fully_shown_at_least_the_minimum_hold():
    from services import tuning
    from services.vdoprocessing.spatial_renderer.popups import _PopupMixin

    fps = 30
    for asked in (0.3, 2.0, 8.0):  # a very short leg, the old floor, a long one
        bp = _PopupMixin._make_baked_popup(
            {"data": {}}, asked, fps, min_hold_seconds=tuning.OVERVIEW_POPUP_MIN_HOLD_SECONDS
        )
        fully_shown = bp["total_frames"] - 2 * bp["fade_frames"]
        assert fully_shown >= int(tuning.OVERVIEW_POPUP_MIN_HOLD_SECONDS * fps)
    assert _PopupMixin._make_baked_popup({"data": {}}, 8.0, fps)["total_frames"] == 8 * fps  # long ones untouched
    # a card over a frozen map (a stop-by batch) keeps its own length: the
    # floor would lengthen the freeze itself
    assert _PopupMixin._make_baked_popup({"data": {}}, 2.0, fps)["total_frames"] == 2 * fps


def test_stops_close_together_are_not_rushed():
    """Stops a few hundred metres apart (natural spacing 0.3s) are still
    walked at least min_leg_frames apart - reached late rather than flashed past."""
    from services.vdoprocessing.spatial_renderer.overview_timing import stop_targets

    natural = {1: 30, 2: 39, 3: 48, 4: 57}
    targets = stop_targets(natural, {"1": 1.0, "4": 2.2}, 0, 30, 2000, min_leg_frames=60)
    gaps = [targets[n + 1] - targets[n] for n in range(1, 4)]
    assert all(g >= 60 for g in gaps)
