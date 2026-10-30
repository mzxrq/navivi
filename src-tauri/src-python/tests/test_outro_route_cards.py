from services.vdoprocessing.outrocard import route_cards

S, A, B, C = [34.0, 135.0], [34.1, 135.1], [34.2, 135.2], [34.3, 135.3]


def leg(frm, to):
    return {"from_at": frm, "to_at": to}


def test_start_first_then_stops_and_the_end():
    assert route_cards([leg(S, A), leg(A, B), leg(B, C)]) == [("S", None), ("1", 0), ("2", 1), ("E", 2)]


def test_return_stops_are_left_out_and_a_round_trip_shows_the_start_only():
    legs = [leg(S, A), leg(A, B), leg(B, A), leg(A, S)]
    assert route_cards(legs) == [("S", None), ("1", 0), ("2", 1)]
