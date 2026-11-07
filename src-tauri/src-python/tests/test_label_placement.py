from services.vdoprocessing.pydeckrecorder.pin_icons import label_offset

MPP = 1.0  # 1 m per pixel
DEG_LAT = 1 / 110540  # 1 m north


def _place(path):
    return label_offset(35.0, 135.0, 100, 30, path, MPP, below=8, above=64, side=26)


def test_route_going_south_pushes_the_label_off_the_line():
    south = [(35.0 - i * 10 * DEG_LAT, 135.0) for i in range(20)]
    x, y = _place(south)
    assert y < 0 or abs(x) > 50  # above or beside, not hanging over the line below


def test_route_elsewhere_keeps_the_label_below():
    north = [(35.0 + i * 10 * DEG_LAT, 135.0) for i in range(20)]
    assert _place(north) == (0, 8 + 15)
