"""{distance} shows the totals card and holds on it (docs/OVERVIEW_RULES.md 8.10)."""
import numpy as np
import pytest

from services.vdoprocessing.spatial_renderer import SpatialRenderer
from services.vdoprocessing.spatial_renderer.course import _course_timing

FPS = 30
CARD = np.zeros((10, 10, 4), np.uint8)


def test_course_totals_come_at_the_distance_cue_and_are_held():
    timing = _course_timing({"end": 10.0, "distance": 14.0}, 12.0, [], [], 100.0, 3.0)
    assert timing.stats_at == 14.0 and timing.end_at >= 17.0  # the voice is shorter than the hold


@pytest.mark.parametrize("cues, at", [({"end": 10.0}, 10.0), ({"end": 10.0, "extras": 20.0}, 10.0)])
def test_course_totals_come_at_the_end_without_a_distance_cue(cues, at):
    assert _course_timing(cues, 30.0, [], [], 100.0).stats_at == at


class _Video:
    def __init__(self, seconds):
        self.frames_written = int(seconds * FPS)

    def write(self, frame):
        self.frames_written += 1

    @property
    def seconds(self):
        return self.frames_written / FPS


def _walk():
    renderer = SpatialRenderer.__new__(SpatialRenderer)
    renderer.config = {"overview_recap_hold_seconds": 3.0}
    renderer.last_frame = np.zeros((4, 4, 3), np.uint8)
    return renderer


@pytest.mark.parametrize("cues, until", [({"distance": 14.0}, 14.0), ({}, 10.0), ({"distance": 8.0}, 10.0)])
def test_walk_totals_card_waits_for_the_distance_cue(cues, until):
    video = _Video(10.0)
    _walk()._ov_wait_for_distance(video, cues, FPS)
    assert video.seconds == pytest.approx(until, abs=1 / FPS)


@pytest.mark.parametrize("zoom_follows", [True, False])
def test_walk_totals_are_held_after_the_distance_cue_before_anything_else(zoom_follows):
    video = _Video(14.5)  # the card has just faded in
    _walk()._ov_hold_summary(video, CARD, {"distance": 14.0}, 0.5, zoom_follows, FPS)
    assert video.seconds == pytest.approx(17.0, abs=1 / FPS)


def test_walk_hold_is_as_before_without_a_distance_cue():
    video = _Video(14.5)
    _walk()._ov_hold_summary(video, CARD, {}, 2.0, True, FPS)
    assert video.seconds == pytest.approx(16.5, abs=1 / FPS)
