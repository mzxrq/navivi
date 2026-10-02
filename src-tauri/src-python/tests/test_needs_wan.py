"""needs_wan (attraction_step.py): the shared ComfyUI queue is only cleared
when a run will actually use Wan - an all-stills run used to interrupt
another process's Wan job mid-sampling (2026-10-02)."""

from services.vdoprocessing.videopipeline.attraction_step import needs_wan


def _wp(**kw):
    return {"label": "西ノ庄駅", "popup_image": ["a.jpg"], **kw}


def test_all_stills_need_no_wan():
    assert not needs_wan([_wp(camera_pans=["none"]), _wp(camera_pans=["None"])])


def test_a_moving_preset_needs_wan():
    assert needs_wan([_wp(camera_pans=["none"]), _wp(camera_pans=["zoom-in"])])


def test_no_preset_falls_back_to_a_wan_prompt():
    assert needs_wan([_wp()])


def test_no_photo_or_own_videos_need_no_wan():
    assert not needs_wan([
        {"label": "x", "camera_pans": ["panright"]},
        _wp(camera_pans=["panright"], videos=["v.mp4"]),
    ])
