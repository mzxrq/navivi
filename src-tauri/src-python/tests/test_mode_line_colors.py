from services.vdoprocessing.videopipeline.render_step import _mode_line_color_overrides


def test_route_line_color_applies_to_every_ordinary_mode():
    overrides = _mode_line_color_overrides({"line_color": [10, 20, 30]})
    for mode in ("walking", "driving", "car", "ferry"):
        assert tuple(overrides[mode]) == (30, 20, 10)
    assert "airplane" not in overrides


def test_per_mode_color_wins_over_route_line_color():
    overrides = _mode_line_color_overrides(
        {"line_color": [10, 20, 30], "mode_line_colors": {"ferry": [1, 2, 3]}}
    )
    assert tuple(overrides["ferry"]) == (3, 2, 1)
    assert tuple(overrides["walking"]) == (30, 20, 10)


def test_no_route_line_color_keeps_mode_defaults():
    assert _mode_line_color_overrides({}) == {}
