from services.vdoprocessing.pydeckrecorder.pin_icons import LabelSpace, label_offset

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


def test_a_second_label_at_the_same_spot_moves_off_the_first():
    # Two points 10 m apart, the route well clear of both: each would hang below its point and cover the other.
    far = [(35.1 + i * 10 * DEG_LAT, 135.1) for i in range(20)]
    space = LabelSpace(35.0, 135.0, MPP)
    first = label_offset(35.0 + 10 * DEG_LAT, 135.0, 100, 30, far, MPP, 8, 64, 26, space)
    second = label_offset(35.0, 135.0, 100, 30, far, MPP, 8, 64, 26, space)
    assert first == (0, 8 + 15)
    assert second != first and len(space.boxes) == 2
    # The two pills (each 100 x 30 around its own centre) no longer touch.
    (ax, ay), (bx, by) = space.boxes[0][:2], space.boxes[1][:2]
    assert abs(ax - bx) >= 100 or abs(ay - by) >= 30


def test_a_label_keeps_off_another_places_pin():
    # A landmark 12 m west of a stop: its name would hang below, straight over that stop's 60 px pin.
    far = [(35.1 + i * 10 * DEG_LAT, 135.1) for i in range(20)]
    space = LabelSpace(35.0, 135.0, MPP)
    space.pin(35.0, 135.0, 45, 60, anchor_bottom=True)  # the stop's teardrop pin, tip on the point
    x, y = label_offset(35.0, 135.0 - 12 * DEG_LAT / 0.819, 100, 30, far, MPP, 10, 10, 12, space)
    assert not (abs(x) < 72 and -60 < y < 15)  # not sitting on the pin


def test_a_landmarks_own_name_still_hangs_under_its_dot():
    far = [(35.1 + i * 10 * DEG_LAT, 135.1) for i in range(20)]
    space = LabelSpace(35.0, 135.0, MPP)
    space.pin(35.0, 135.0, 14, 14)  # its own dot, which the pill is meant to sit right under
    assert label_offset(35.0, 135.0, 100, 26, far, MPP, 10, 10, 12, space) == (0, 10 + 13)


def _apart(a, b) -> bool:
    return a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3]


def test_more_labels_than_spots_stack_further_out():
    # Five names on one point: the four spots around it, then a row stacked beyond them - never one on another.
    far = [(35.1 + i * 10 * DEG_LAT, 135.1) for i in range(20)]
    space = LabelSpace(35.0, 135.0, MPP)
    offsets = [label_offset(35.0, 135.0, 100, 30, far, MPP, 8, 64, 26, space) for _ in range(5)]
    assert len(set(offsets)) == 5
    assert all(_apart(a, b) for i, a in enumerate(space.boxes) for b in space.boxes[i + 1:])
