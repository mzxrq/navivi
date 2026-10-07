import json

import pandas as pd
import pytest

from services.mapfetcher.maplanguage import map_style_inputs, resolve_map_style

GL = "mapbox://styles/"


def test_absent_setting_keeps_each_steps_own_style():
    for settings in (None, {}, {"mapbox_style_id": ""}, {"mapbox_style_id": None}):
        assert resolve_map_style(settings, "mapbox/outdoors-v12") == GL + "mapbox/outdoors-v12"
        assert resolve_map_style(settings, "mapbox/streets-v12", raster=True) == "mapbox/streets-v12"


def test_chosen_style_wins_in_gl_and_raster_steps():
    s = {"mapbox_style_id": "mapbox/satellite-streets-v12"}
    assert resolve_map_style(s, "mapbox/outdoors-v12") == GL + "mapbox/satellite-streets-v12"
    assert resolve_map_style(s, "mapbox/streets-v12", raster=True) == "mapbox/satellite-streets-v12"


def test_full_url_and_stray_slashes_are_normalised():
    s = {"mapbox_style_id": GL + "mapbox/dark-v11/"}
    assert resolve_map_style(s, "mapbox/outdoors-v12") == GL + "mapbox/dark-v11"
    assert resolve_map_style(s, "mapbox/streets-v12", raster=True) == "mapbox/dark-v11"


@pytest.mark.parametrize("bad", ["dark-v11", "a/b/c", "mapbox/", "/x", "my style/x", 5])
def test_malformed_style_falls_back_to_the_default(bad):
    assert resolve_map_style({"mapbox_style_id": bad}, "mapbox/outdoors-v12") == GL + "mapbox/outdoors-v12"


def test_raster_tiles_prefer_the_language_studio_style():
    s = {"mapbox_style_id": "mapbox/dark-v11", "mapbox_style_id_ja": "me/ja-style"}
    assert resolve_map_style(s, "mapbox/streets-v12", "ja", raster=True) == "me/ja-style"
    assert resolve_map_style(s, "mapbox/streets-v12", "en", raster=True) == "mapbox/dark-v11"
    assert resolve_map_style(s, "mapbox/outdoors-v12", "ja") == GL + "mapbox/dark-v11"


def test_style_inputs_are_empty_for_a_project_that_sets_nothing():
    assert map_style_inputs(None) == ""
    assert map_style_inputs({"mapbox_retina": True, "other": 1}) == ""
    assert map_style_inputs({"mapbox_style_id": "mapbox/dark-v11"}) != ""
    assert map_style_inputs({"mapbox_retina": False}) != ""
    assert map_style_inputs({"mapbox_style_id": "mapbox/dark-v11"}) != map_style_inputs({"mapbox_style_id": "mapbox/light-v11"})


def test_map_style_changes_the_route_checkpoint_only_when_set(tmp_path):
    from services.vdoprocessing.videopipeline import render_step

    route = {"route": pd.DataFrame({"latitude": [35.0, 35.1], "longitude": [139.0, 139.1]}), "summary": {}}

    def parts(settings):
        cfg = tmp_path / "job_config.json"
        cfg.write_text(json.dumps({"waypoints": [], "settings": settings}), encoding="utf-8")
        return render_step._checkpoint_parts(str(cfg), route, [], [])

    plain, same, dark = parts({"fps": 30}), parts({"fps": 30, "mapbox_retina": True}), parts({"mapbox_style_id": "mapbox/dark-v11"})
    assert "route.map_style" not in plain and plain.get("route.map_style") == same.get("route.map_style")
    assert dark["route.map_style"] and "route.map_style" in render_step.ROUTE_CHECKPOINT_PARTS


def test_raster_provider_uses_the_chosen_style_and_retina(monkeypatch):
    from services.mapfetcher import maptile

    monkeypatch.setattr(maptile, "resolve_mapbox_token", lambda settings: "tok")
    fetcher = object.__new__(maptile.TileDownloader)
    fetcher.job_config = None
    fetcher.MAX_ZOOM_LEVEL = 20
    default = fetcher._build_provider({})
    assert default["id"] == "mapbox/streets-v12" and default["r"] == "@2x"
    chosen = fetcher._build_provider({"mapbox_style_id": "mapbox/dark-v11", "mapbox_retina": False})
    assert chosen["id"] == "mapbox/dark-v11" and chosen["r"] == ""
