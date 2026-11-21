"""A leg's stop-bys go on their own pill; the place chain keeps the start, stops and destination."""

from services.vdoprocessing.route2vdo import _split_stopby_chain


def test_stopbys_split_out_of_chain():
    res = {
        "labels": ["Start", "A", "Stop1", "B", "Stop2", "Dest"],
        "stopbys": [False, False, True, False, True, False],
    }
    assert _split_stopby_chain(res) == (["Start", "A", "B", "Dest"], ["Stop1", "Stop2"])


def test_destination_stays_in_chain_even_if_stopby():
    res = {"labels": ["Start", "Stop"], "stopbys": [False, True]}
    assert _split_stopby_chain(res) == (["Start", "Stop"], [])


def test_closed_points_and_missing_flags():
    assert _split_stopby_chain({"labels": ["A", None, "B"]}) == (["A", "B"], [])
    assert _split_stopby_chain({}) == ([], [])
