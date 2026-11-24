"""A leg's stop-bys are listed with the chain place they come before and where they sit; the chain keeps the start, stops and destination."""

from services.vdoprocessing.route2vdo import _split_stopby_chain


def test_stopbys_split_out_of_chain():
    res = {
        "labels": ["Start", "A", "Stop1", "B", "Stop2", "Dest"],
        "stopbys": [False, False, True, False, True, False],
        "lats": [0, 1, 2, 3, 4, 5],
        "lons": [10, 11, 12, 13, 14, 15],
    }
    assert _split_stopby_chain(res) == (
        ["Start", "A", "B", "Dest"], [["Stop1", 2, 2.0, 12.0], ["Stop2", 3, 4.0, 14.0]],
    )


def test_stopby_position_is_none_when_points_do_not_line_up():
    res = {"labels": ["S", "X", "D"], "stopbys": [False, True, False], "lats": [0, 1], "lons": [0, 1]}
    assert _split_stopby_chain(res) == (["S", "D"], [["X", 1, None, None]])


def test_destination_stays_in_chain_even_if_stopby():
    res = {"labels": ["Start", "Stop"], "stopbys": [False, True]}
    assert _split_stopby_chain(res) == (["Start", "Stop"], [])


def test_closed_points_and_missing_flags():
    assert _split_stopby_chain({"labels": ["A", None, "B"]}) == (["A", "B"], [])
    assert _split_stopby_chain({}) == ([], [])
