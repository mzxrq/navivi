"""The Mapbox token is app-wide: NAVIVI_MAPBOX_TOKEN first, then a legacy project setting, then the old env names."""

import pytest

from services.mapbox_token import ENV_VAR, resolve_mapbox_token

ALL_ENV = (ENV_VAR, "MAPBOX_API_KEY", "MAPBOX_ACCESS_TOKEN", "VITE_MAPBOX_TOKEN")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ALL_ENV:
        monkeypatch.delenv(name, raising=False)


def test_nothing_configured_gives_none():
    assert resolve_mapbox_token() is None
    assert resolve_mapbox_token({}) is None
    assert resolve_mapbox_token({"mapbox_api_key": "  "}) is None


def test_app_token_beats_everything(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "app")
    monkeypatch.setenv("MAPBOX_API_KEY", "old-env")
    monkeypatch.setenv("VITE_MAPBOX_TOKEN", "vite")
    assert resolve_mapbox_token({"mapbox_api_key": "project"}) == "app"


def test_legacy_project_setting_beats_the_old_env_names(monkeypatch):
    monkeypatch.setenv("MAPBOX_API_KEY", "old-env")
    assert resolve_mapbox_token({"mapbox_api_key": "project"}) == "project"
    assert resolve_mapbox_token({"mapbox_access_token": "older"}) == "older"
    assert resolve_mapbox_token({}) == "old-env"


def test_old_env_names_keep_their_order(monkeypatch):
    monkeypatch.setenv("VITE_MAPBOX_TOKEN", "vite")
    assert resolve_mapbox_token() == "vite"
    monkeypatch.setenv("MAPBOX_ACCESS_TOKEN", "access")
    assert resolve_mapbox_token() == "access"
    monkeypatch.setenv("MAPBOX_API_KEY", "key")
    assert resolve_mapbox_token() == "key"


def test_whitespace_is_trimmed(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "  pk.abc \n")
    assert resolve_mapbox_token() == "pk.abc"


def test_the_tile_provider_uses_the_app_token(monkeypatch, tmp_path):
    from services.mapfetcher.maptile import TileDownloader

    monkeypatch.setenv(ENV_VAR, "pk.from-app")
    config = {"directory_path": str(tmp_path), "settings": {"mapbox_api_key": "pk.legacy"}}
    downloader = TileDownloader(config)
    assert downloader.provider["accessToken"] == "pk.from-app"

    monkeypatch.delenv(ENV_VAR)
    assert TileDownloader(config).provider["accessToken"] == "pk.legacy"


def test_a_leg_render_finds_a_legacy_key_in_the_job_config(monkeypatch):
    from types import SimpleNamespace

    from services.vdoprocessing.route2vdo import RouteAnimator

    animator = RouteAnimator.__new__(RouteAnimator)
    animator.spatial_renderer = SimpleNamespace(_get_job_config=lambda: {"settings": {"mapbox_api_key": "pk.legacy"}})
    assert animator._mapbox_token() == "pk.legacy"
    monkeypatch.setenv(ENV_VAR, "pk.app")
    assert animator._mapbox_token() == "pk.app"

    animator.spatial_renderer = SimpleNamespace(_get_job_config=lambda: None)
    monkeypatch.delenv(ENV_VAR)
    assert animator._mapbox_token() is None
