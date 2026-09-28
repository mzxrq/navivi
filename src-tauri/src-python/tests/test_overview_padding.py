"""_adaptive_overview_padding: picks the overview map's bounding-box padding
from the route's own span, reading the (span_km, padding) table from
tuning.OVERVIEW_PADDING_BY_SPAN_KM/OVERVIEW_PADDING_MAX_SPAN rather than a
local constant - the actual lever for how much surrounding map the overview
shows (not a zoom-level fudge, which mostly rounds up to the same level
regardless)."""

import pandas as pd
import pytest

from services import tuning
from services.vdoprocessing.videopipeline.render_step import _adaptive_overview_padding


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

    def test_padding_is_monotonically_non_decreasing_with_span(self):
        # Each successive tier should never ask for LESS padding than the
        # one before it - a bigger route should never get a tighter crop.
        paddings = [p for _, p in tuning.OVERVIEW_PADDING_BY_SPAN_KM] + [tuning.OVERVIEW_PADDING_MAX_SPAN]
        assert paddings == sorted(paddings)
