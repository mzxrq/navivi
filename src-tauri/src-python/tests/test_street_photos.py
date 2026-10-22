"""Mapillary photos at a leg's turns (services/mapfetcher/street_photos.py), with the API mocked."""

import io
import json

import pytest
import requests
from PIL import Image

from services.mapfetcher import street_photos
from tests.test_leg_script import _at, _path

L_LEG = _path((0, 0), (400, 0), (400, 100))  # east, then a left turn north
Z_LEG = _path((0, 0), (400, 0), (400, 300), (700, 300))  # two turns


class _Resp:
    def __init__(self, data=None, content=b"", status=200):
        self._data, self.content, self.status = data, content, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status}")

    def json(self):
        return self._data


def _jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), "gray").save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def api(monkeypatch):
    """Records every request; `api.images` is what a search returns, `api.status` its HTTP status."""
    class Api:
        images, status, calls = [], 200, []

    def get(url, timeout=None, params=None):
        Api.calls.append(url)
        if params is not None:
            assert params["limit"] <= 10 and "bbox" in params
            return _Resp({"data": Api.images}, status=Api.status)
        return _Resp(content=_jpeg())

    Api.calls = []
    monkeypatch.setattr(street_photos.requests, "get", get)
    monkeypatch.setattr(street_photos.time, "sleep", lambda s: None)
    return Api


def _image(img_id, angle, at=(400, 0)):
    lat, lon = _at(*at)
    return {"id": img_id, "thumb_1024_url": f"https://x/{img_id}", "compass_angle": angle,
            "geometry": {"coordinates": [lon, lat]}}


def test_the_photo_facing_the_new_street_is_picked(tmp_path, api):
    api.images = [_image("east", 90), _image("north", 5)]
    photos = street_photos.turn_photos(L_LEG, tmp_path, "token")
    assert len(photos) == 1 and photos[0]["popup_image"].endswith("north.jpg")
    assert Image.open(photos[0]["popup_image"]).size == (64, 48)


def test_an_unchanged_route_makes_no_requests(tmp_path, api):
    api.images = [_image("north", 5)]
    first = street_photos.turn_photos(L_LEG, tmp_path, "token")
    api.calls.clear()
    assert street_photos.turn_photos(L_LEG, tmp_path, "token") == first
    assert api.calls == []


def test_no_coverage_is_remembered(tmp_path, api):
    assert street_photos.turn_photos(L_LEG, tmp_path, "token") == []
    api.calls.clear()
    street_photos.turn_photos(L_LEG, tmp_path, "token")
    assert api.calls == []


def test_a_refusal_stops_requests_but_keeps_cached_turns(tmp_path, api):
    api.images = [_image("north", 5)]
    assert len(street_photos.turn_photos(Z_LEG, tmp_path, "token")) == 2
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    del index[next(iter(index))]  # forget the first turn only
    (tmp_path / "index.json").write_text(json.dumps(index), encoding="utf-8")
    api.status, api.calls = 429, []
    assert len(street_photos.turn_photos(Z_LEG, tmp_path, "token")) == 1  # the second turn, from the index
    assert len(api.calls) == 1  # the refused search, nothing after it


def test_a_zigzag_loads_one_photo(tmp_path, api):
    api.images = [_image("any", 0)]
    zigzag = _path((0, 0), (200, 0), (200, 40), (260, 40), (260, 80), (500, 80))  # four bends within 100 m
    assert len(street_photos.turn_photos(zigzag, tmp_path, "token")) == 1
    assert len(api.calls) == 2  # one search, one download
