"""A leg's narration pieces target only the stop-bys it is really cut at (fix.md #2)."""

from services.vdoprocessing.route2vdo import cut_landmark_ids


def test_only_stopbys_with_an_existing_photo_take_a_piece(tmp_path):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    markers = [
        {"waypoint_id": "no_photo", "lat": 1, "lng": 2},
        {"waypoint_id": "connected", "lat": 1, "lng": 2, "connect_to_route": True, "popup_image": str(photo)},
        {"waypoint_id": "passed", "lat": 1, "lng": 2, "popup_image": str(photo)},
        {"waypoint_id": "missing_file", "lat": 1, "lng": 2, "popup_image": str(tmp_path / "gone.jpg")},
    ]
    assert cut_landmark_ids(markers) == ["connected", "passed"]


def test_a_renamed_stop_or_new_timing_re_renders_the_leg_but_old_records_are_kept():
    from services.vdoprocessing.route2vdo import leg_changed_parts

    old = {"route_inputs": "r", "render_version": "8", "kw.route_chain": "AB", "kw.target_duration_seconds": "9"}
    assert leg_changed_parts(dict(old), old) == []
    assert leg_changed_parts({**old, "kw.route_chain": "AC"}, old) == ["kw.route_chain"]  # stop renamed
    assert leg_changed_parts({**old, "kw.target_duration_seconds": "12"}, old) == ["kw.target_duration_seconds"]
    # recorded before the start cue was checked: not a reason to render it again
    assert leg_changed_parts({**old, "kw.start_cue_seconds": "1.5"}, old) == []
