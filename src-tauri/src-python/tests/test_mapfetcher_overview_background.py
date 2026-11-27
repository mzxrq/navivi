"""The overview video's background is the deck.gl capture in every style; the capture is faked (CPU only)."""

import pytest

from services import tuning
from services.mapfetcher import mapfetcher, pydeck_overview
from services.mapfetcher.mapfetcher import MapFetcher

BBOX = {"min_lat": 34.24, "max_lat": 34.30, "min_lon": 135.02, "max_lon": 135.14}
EXTENT = (0.0, 1.0, 0.0, 1.0)


class _Raster:
    def fetch_overview_image(self, bbox, path, size, max_zoom):
        return path, EXTENT, size


def _fetcher(tmp_path, **settings):
    fetcher = MapFetcher.__new__(MapFetcher)
    fetcher.config = {"directory_path": str(tmp_path), "settings": settings}
    fetcher.downloader = _Raster()
    return fetcher


@pytest.fixture
def captures(monkeypatch):
    """The deck.gl capture, recorded instead of run, with a token present."""
    calls = []

    def fake(bbox, path, size, **kwargs):
        calls.append((path, kwargs))
        return path, EXTENT, size

    monkeypatch.setattr(pydeck_overview, "fetch_overview_image_pydeck", fake)
    monkeypatch.setattr(mapfetcher, "resolve_mapbox_token", lambda settings: "pk.test")
    return calls


@pytest.mark.parametrize("style", tuning.OVERVIEW_STYLES)
def test_every_style_is_drawn_on_the_3d_map(tmp_path, captures, style):
    path, _, _ = _fetcher(tmp_path, overview_style=style).fetch_image(BBOX, "map.png")
    assert [c[0] for c in captures] == [path]


def test_an_old_raster_choice_no_longer_changes_the_video_map(tmp_path, captures):
    _fetcher(tmp_path, overview_background="raster").fetch_image(BBOX, "map.png")
    assert len(captures) == 1


def test_no_token_stops_with_an_error_that_says_so(tmp_path, captures, monkeypatch):
    monkeypatch.setattr(mapfetcher, "resolve_mapbox_token", lambda settings: None)
    with pytest.raises(RuntimeError, match="Mapbox token"):
        _fetcher(tmp_path).fetch_image(BBOX, "map.png")
    assert captures == []


def test_a_failed_capture_stops_with_its_reason_and_draws_no_raster_map(tmp_path, captures, monkeypatch):
    def broken(*a, **k):
        raise OSError("browser gone")

    monkeypatch.setattr(pydeck_overview, "fetch_overview_image_pydeck", broken)
    with pytest.raises(RuntimeError, match="browser gone"):
        _fetcher(tmp_path).fetch_image(BBOX, "map.png")


def test_a_caller_that_is_not_the_video_may_ask_for_the_raster_map(tmp_path, captures, monkeypatch):
    monkeypatch.setattr(mapfetcher, "resolve_mapbox_token", lambda settings: None)
    path, extent, _ = _fetcher(tmp_path).fetch_image(BBOX, "map.png", raster=True)
    assert captures == [] and extent == EXTENT and path.endswith("map.png")
