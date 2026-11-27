"""Legs and connected stop-bys show the attraction clip's end frames in place of the photo."""

import pytest

from services.vdoprocessing import route2vdo
from services.vdoprocessing.videopipeline.helpers import attraction_output_filename


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(route2vdo, "clip_end_frames", lambda clip, out: (clip + ".first", clip + ".last"))
    attraction = tmp_path / "attraction"
    attraction.mkdir()
    waypoints = [{"id": i, "label": i, "attractionNarration": "text"} for i in ("a", "b")]
    clips = {}
    for idx, wp in enumerate(waypoints):
        path = attraction / attraction_output_filename(idx, wp["label"])
        path.write_bytes(b"x")
        clips[wp["id"]] = str(path)
    animator = route2vdo.RouteAnimator.__new__(route2vdo.RouteAnimator)
    animator.config = {"res_route_path": str(tmp_path / "job_config.json"), "enable_attraction_videos": True}
    ctx = route2vdo._ResContext({w["id"]: w for w in waypoints}, {"a": 0, "b": 1}, attraction, None, {}, [], [])
    return animator, ctx, clips


def _leg(**over):
    return {"start_waypoint_id": "a", "end_waypoint_id": "b", "popups": [{"popup_image": "b.jpg"}],
            "leg_start_popup": {"popup_image": "a.jpg"}, **over}


def _stopby(**over):
    return {"lat": 34.0, "lng": 135.0, "label": "b", "waypoint_id": "b", "connect_to_route": True,
            "popup_image": "b.jpg", **over}


def test_leg_ends_on_the_next_clips_first_frame_and_opens_on_the_last_clips_last(setup):
    animator, ctx, clips = setup
    photos = animator._leg_photos(ctx, _leg())
    assert photos.dest_image == clips["b"] + ".first"
    assert photos.start_image == clips["a"] + ".last"


def test_a_connected_stopby_gets_both_frames(setup):
    animator, ctx, clips = setup
    entry = animator._landmark_entry(ctx, _stopby())
    assert (entry["popup_image"], entry["popup_image_after"], entry["attraction_video"]) == (
        clips["b"] + ".first", clips["b"] + ".last", clips["b"])
    assert "dissolve_into_attraction" not in entry


@pytest.mark.parametrize("case", ["off", "missing", "unreadable"])
def test_without_a_usable_clip_the_photos_stay(setup, monkeypatch, case):
    animator, ctx, clips = setup
    if case == "off":
        animator.config["enable_attraction_videos"] = False
    elif case == "missing":
        for path in clips.values():
            route2vdo.Path(path).unlink()
    else:
        monkeypatch.setattr(route2vdo, "clip_end_frames", lambda clip, out: None)
    photos = animator._leg_photos(ctx, _leg())
    assert (photos.dest_image, photos.start_image) == ("b.jpg", "a.jpg")
    entry = animator._landmark_entry(ctx, _stopby())
    assert entry["popup_image"] == "b.jpg" and entry["attraction_video"] is None
    assert "popup_image_after" not in entry


def test_return_stops_passed_places_and_photoless_stops_are_left_alone(setup):
    animator, ctx, _ = setup
    assert animator._leg_photos(ctx, _leg(dest_is_return=True)).dest_image == "b.jpg"
    assert animator._landmark_entry(ctx, _stopby(connect_to_route=False))["popup_image"] == "b.jpg"
    assert animator._landmark_entry(ctx, _stopby(popup_image=None))["popup_image"] is None
    bare = animator._leg_photos(ctx, _leg(popups=[], leg_start_popup={}))
    assert (bare.dest_image, bare.start_image) == (None, None)
