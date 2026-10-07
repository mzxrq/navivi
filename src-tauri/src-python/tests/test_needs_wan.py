"""needs_wan (attraction_step.py): the shared ComfyUI queue is only cleared
when a run will actually use Wan - an all-stills run used to interrupt
another process's Wan job mid-sampling (2026-10-02)."""

from services.vdoprocessing.videopipeline.attraction_step import (
    _resolve_attraction_prompt, generate_waypoint_attraction_video, needs_wan,
)


def _wp(**kw):
    return {"label": "西ノ庄駅", "popup_image": ["a.jpg"], **kw}


def test_all_stills_need_no_wan():
    assert not needs_wan([_wp(imagePans=["none"]), _wp(imagePans=["None"])])


def test_a_moving_preset_needs_wan():
    assert needs_wan([_wp(imagePans=["none"]), _wp(imagePans=["pan-right"])])


def test_jump_cuts_need_no_wan():
    assert not needs_wan([_wp(imagePans=["zoom-in"]), _wp(imagePans=["zoom-out"])])


def test_no_preset_falls_back_to_a_wan_prompt():
    assert needs_wan([_wp()])


def test_no_photo_or_own_videos_need_no_wan():
    assert not needs_wan([
        {"label": "x", "imagePans": ["panright"]},
        _wp(imagePans=["panright"], videos=["v.mp4"]),
    ])


def test_one_pan_per_photo_from_image_pans():
    wp = _wp(images=["a.jpg", "b.jpg"], imagePans=["pan-right", "walk-in", "none"])
    assert _resolve_attraction_prompt(wp) == ["pan-right", "walk-in"]
    assert _resolve_attraction_prompt(_wp(images=["a.jpg", "b.jpg"], imagePans=["zoom-out"])) == ["zoom-out", "panright"]
    assert _resolve_attraction_prompt(_wp(images=["a.jpg"])) == ["panright"]


class _Generator:
    def __init__(self):
        self.photos = None

    def process_attraction_video(self, popup_image_entry, **kw):
        self.photos = popup_image_entry
        return "out.mp4"


def test_every_photo_reaches_the_generator():
    # The editor keeps only the first photo in popup_image; the second one was dropped.
    gen = _Generator()
    generate_waypoint_attraction_video(_wp(images=["a.jpg", "b.jpg"], imagePans=["walk-in", "pan-right"]), 0, gen)
    assert gen.photos == ["a.jpg", "b.jpg"]
    generate_waypoint_attraction_video(_wp(), 0, gen)
    assert gen.photos == ["a.jpg"]


def test_projects_saved_with_camera_pans_still_work():
    assert _resolve_attraction_prompt(_wp(camera_pans=["pan-left"])) == ["pan-left"]
    assert _resolve_attraction_prompt(_wp(camera_pans=["pan-left"], imagePans=["zoom-in"])) == ["zoom-in"]
