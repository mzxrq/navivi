"""A residential leg is only reused when what it was rendered from is unchanged."""

import numpy as np

from services.vdoprocessing.route2vdo import _leg_fingerprint, _stored_fingerprint

LATLON = np.array([[34.27, 135.07], [34.28, 135.08]])


def test_same_inputs_same_fingerprint():
    a = _leg_fingerprint(LATLON, "石標", {"target_duration_seconds": 8.0})
    b = _leg_fingerprint(LATLON.copy(), "石標", {"target_duration_seconds": 8.0})
    assert a == b


def test_a_new_walk_timing_changes_it():
    a = _leg_fingerprint(LATLON, "石標", {"target_duration_seconds": 8.0, "arrival_wait_seconds": 2.0})
    b = _leg_fingerprint(LATLON, "石標", {"target_duration_seconds": 6.7, "arrival_wait_seconds": 9.0})
    assert a != b


def test_the_whole_route_piece_counts():
    moved = LATLON.copy()
    moved[1, 0] += 0.001
    assert _leg_fingerprint(LATLON, "石標", {}) != _leg_fingerprint(moved, "石標", {})


def test_missing_or_broken_sidecar_reads_as_none(tmp_path):
    assert _stored_fingerprint(tmp_path / "none.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert _stored_fingerprint(bad) is None
