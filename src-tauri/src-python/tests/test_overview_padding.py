"""_adaptive_overview_padding: picks the overview map's bounding-box padding
from the route's own span, reading the (span_km, padding) table from
tuning.OVERVIEW_PADDING_BY_SPAN_KM/OVERVIEW_PADDING_MAX_SPAN rather than a
local constant - the actual lever for how much surrounding map the overview
shows (not a zoom-level fudge, which mostly rounds up to the same level
regardless)."""

import pandas as pd
import pytest

from services import tuning
from services.vdoprocessing.videopipeline.overview_framing import _adaptive_overview_padding


def _route_df(min_lat, min_lon, max_lat, max_lon):
    return pd.DataFrame({
        "latitude": [min_lat, max_lat],
        "longitude": [min_lon, max_lon],
    })


class TestAdaptiveOverviewPadding:
    def test_reads_the_table_from_tuning_not_a_local_constant(self):
        # A tiny route (well under the first span ceiling) gets the first
        # table entry's padding.
        df = _route_df(35.0, 139.0, 35.001, 139.001)  # ~140m span
        assert _adaptive_overview_padding(df) == tuning.OVERVIEW_PADDING_BY_SPAN_KM[0][1]

    def test_a_huge_span_falls_back_to_the_max_padding(self):
        df = _route_df(35.0, 139.0, 36.0, 140.0)  # well over every ceiling
        assert _adaptive_overview_padding(df) == tuning.OVERVIEW_PADDING_MAX_SPAN

    def test_falls_back_to_a_flat_10_percent_when_span_cant_be_computed(self):
        # Missing the lat/lon columns entirely (e.g. a malformed route) -
        # KeyError inside the try block, not a computable (even zero) span.
        assert _adaptive_overview_padding(pd.DataFrame({"x": [1]})) == pytest.approx(0.10)

    def test_span_ceilings_are_sorted_so_the_first_match_wins_correctly(self):
        # The lookup returns the FIRST tier whose ceiling the span fits under,
        # so the ceilings must ascend. The padding values themselves are free
        # to be tuned in any shape (a mid-size route may want more than a big one).
        ceilings = [c for c, _ in tuning.OVERVIEW_PADDING_BY_SPAN_KM]
        assert ceilings == sorted(ceilings)


class TestCrowdedRoutePadding:
    """Many stops need room for their cards whatever the route's span, so the
    span's padding is widened per stop above the threshold."""

    def test_a_few_stops_leave_the_span_padding_alone(self):
        df = _route_df(35.0, 139.0, 35.001, 139.001)
        base = tuning.OVERVIEW_PADDING_BY_SPAN_KM[0][1]
        assert _adaptive_overview_padding(df, tuning.OVERVIEW_PADDING_CROWD_STOPS) == base

    def test_every_stop_above_the_threshold_widens_the_frame(self):
        df = _route_df(35.0, 139.0, 35.001, 139.001)
        base = tuning.OVERVIEW_PADDING_BY_SPAN_KM[0][1]
        stops = tuning.OVERVIEW_PADDING_CROWD_STOPS + 4
        assert _adaptive_overview_padding(df, stops) == pytest.approx(
            base + 4 * tuning.OVERVIEW_PADDING_PER_CROWD_STOP
        )

    def test_it_stops_at_the_ceiling(self):
        df = _route_df(35.0, 139.0, 36.0, 140.0)  # already the widest span padding
        assert _adaptive_overview_padding(df, 200) == tuning.OVERVIEW_PADDING_MAX
