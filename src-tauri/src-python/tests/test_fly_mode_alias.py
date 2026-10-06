"""The editor saves a Fly leg as routeMode "curve"; every reader must treat it as an airplane leg."""

from services import tuning
from services.vdoprocessing.pydeckrecorder.legresolve import _resolve_leg
from services.vdoprocessing.pydeckrecorder.pedestrian import _MODE_HUD, _hud_text
from services.vdoprocessing.videopipeline.helpers import _build_point_modes


def _wps(mode):
    return [
        {"lat": 35.0, "lng": 139.0, "routeMode": mode},
        {"lat": 36.0, "lng": 140.0, "routeMode": "walking"},
    ]


def test_curve_aliases_to_airplane_and_old_aliases_stay():
    assert tuning.MODE_ALIASES["curve"] == "airplane"
    assert tuning.MODE_ALIASES["direct"] == "walking"
    assert tuning.MODE_ALIASES["draw"] == "walking"


def test_fly_leg_point_modes_hud_label_and_speed():
    modes = _build_point_modes(4, [0, 2], _wps("curve"))
    assert modes == ["walking", "airplane", "airplane", "airplane"]
    hud = _MODE_HUD.get(modes[2])
    assert hud["time_label"] == "飛行時間"
    assert tuning.REPORTED_MODE_SPEED_KMH[modes[2]] == 500.0
    banner, _ = _hud_text("Tokyo", 5000, 1, 30, mode=modes[2])
    assert banner.endswith("搭乗中")


def test_fly_leg_is_a_2d_fallback_leg():
    assert tuning.MODE_ALIASES["curve"] in tuning.RESIDENTIAL_2D_FALLBACK_MODES


def test_resolve_leg_maps_curve_to_airplane():
    mode, _, _ = _resolve_leg("35.0,139.0|36.0,140.0|curve", _wps("curve"))
    assert mode == "airplane"
