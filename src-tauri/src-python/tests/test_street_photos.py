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
    Image.new("RGB", (640, 480), (128, 128, 128)).save(buf, "JPEG")  # 4:3, like most Mapillary photos
    return buf.getvalue()


@pytest.fixture
def api(monkeypatch):
    """Records every request; `api.images` is what a search returns, `api.status` its HTTP status."""
    class Api:
        images, status, calls = [], 200, []

    def get(url, timeout=None, params=None):
        Api.calls.append(url)
        if url == street_photos.API:
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
            "geometry": {"coordinates": [lon, lat]}, "creator": {"username": "yasunari"}}


def test_the_photo_facing_the_new_street_is_picked(tmp_path, api):
    api.images = [_image("east", 90), _image("north", 5)]
    photos = street_photos.turn_photos(L_LEG, tmp_path, "token")
    assert len(photos) == 1 and photos[0]["popup_image"].endswith("north.jpg")
    card = Image.open(photos[0]["popup_image"]).convert("L")
    assert card.size == (640, 360)  # the card's 16:9, so the card shows all of it
    strip = round(360 * street_photos.CREDIT_STRIP_SHARE)
    assert abs(card.getpixel((10, 10)) - 128) < 8  # the photo fills the top, nothing on it
    assert card.getpixel((10, 360 - strip // 2)) < 40  # the dark credit strip under it
    assert card.crop((0, 360 - strip, 640, 360)).getextrema()[1] > 200  # with the white credit text


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


def test_only_real_turns_away_from_the_stops_are_looked_up(tmp_path, api):
    api.images = [_image("any", 0)]
    gentle = _path((0, 0), (300, 0), (600, 250))  # a 40 deg bend (寄って): no request
    assert street_photos.turn_photos(gentle, tmp_path, "token") == [] and api.calls == []
    at_the_stop = _path((0, 0), (400, 0), (400, 30))  # a sharp turn 30 m before the destination
    assert street_photos.turn_photos(at_the_stop, tmp_path, "token") == [] and api.calls == []
