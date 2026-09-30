"""A mode change applies from the segment it belongs to: point_modes[i] is
the mode of the segment ending at point i (videopipeline.helpers._build_point_modes)."""

from services.vdoprocessing.spatial_renderer.overview_pacing import _OverviewPacingMixin as P


def test_two_point_ferry_leg_is_coloured_as_ferry():
    points = [(0, 0), (10, 0), (20, 0), (30, 0)]
    modes = ["walking", "walking", "ferry", "walking"]  # segment 1->2 is the ferry
    bps = P._build_mode_breakpoints(points, modes)
    assert P._mode_at_fraction(bps, 0.2) == "walking"
    assert P._mode_at_fraction(bps, 0.5) == "ferry"
    assert P._mode_at_fraction(bps, 0.9) == "walking"


def test_first_segment_uses_its_own_mode():
    bps = P._build_mode_breakpoints([(0, 0), (10, 0), (20, 0)], ["walking", "ferry", "walking"])
    assert P._mode_at_fraction(bps, 0.1) == "ferry"
    assert P._mode_at_fraction(bps, 0.9) == "walking"
