"""needs_wan (attraction_step.py): the shared ComfyUI queue is only cleared
when a run will actually use Wan - an all-stills run used to interrupt
another process's Wan job mid-sampling (2026-10-02)."""

from services.vdoprocessing.videopipeline.attraction_step import _resolve_attraction_prompt, needs_wan


def _wp(**kw):
    return {"label": "西ノ庄駅", "popup_image": ["a.jpg"], **kw}


def test_all_stills_need_no_wan():
    assert not needs_wan([_wp(imagePans=["none"]), _wp(imagePans=["None"])])


def test_a_moving_preset_needs_wan():
    assert needs_wan([_wp(imagePans=["none"]), _wp(imagePans=["zoom-in"])])


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


def test_projects_saved_with_camera_pans_still_work():
    assert _resolve_attraction_prompt(_wp(camera_pans=["pan-left"])) == ["pan-left"]
    assert _resolve_attraction_prompt(_wp(camera_pans=["pan-left"], imagePans=["zoom-in"])) == ["zoom-in"]
