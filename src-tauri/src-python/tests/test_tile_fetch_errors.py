"""A refused map key fails at once and says so; other failures step down a zoom and name the last error."""

import pytest
import requests

from services.mapfetcher.maptile import TileDownloader


def _downloader(errors):
    d = object.__new__(TileDownloader)
    calls = []

    def fetch(w, s, e, n, zoom):
        calls.append(zoom)
        err = errors(zoom)
        if err:
            raise err
        return "img", (0, 0, 1, 1)

    d._bounds2img_safe = fetch
    return d, calls


def test_a_refused_key_stops_at_once_without_showing_the_key():
    url = "https://api.mapbox.com/styles/v1/x/tiles/12/401/402?access_token=pk.SECRET"
    d, calls = _downloader(lambda z: requests.HTTPError(f"401 Client Error: Unauthorized for url: {url}"))
    with pytest.raises(RuntimeError) as info:
        d._fetch_stepping_down(0, 0, 1, 1, 12, "overview map tiles")
    assert calls == [12] and "Mapbox key" in str(info.value) and "SECRET" not in str(info.value)


def test_a_missing_zoom_steps_down_and_a_final_failure_names_the_cause():
    d, calls = _downloader(lambda z: requests.HTTPError("404 Client Error: Not Found for url: https://x/12/401/402") if z > 10 else None)
    assert d._fetch_stepping_down(0, 0, 1, 1, 12, "tiles") == ("img", (0, 0, 1, 1))
    assert calls == [12, 11, 10]
    d, _ = _downloader(lambda z: requests.ConnectionError("no network"))
    with pytest.raises(RuntimeError, match="no network"):
        d._fetch_stepping_down(0, 0, 1, 1, 3, "tiles")
