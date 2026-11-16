"""With "AI photo clips" off, each photo can still be ticked for ComfyUI (waypoint.imageAi)."""

from services.vdoprocessing.videopipeline.attraction_step import _resolve_attraction_ai, needs_wan


def _wp(**kw):
    return {"popup_image": ["a.jpg", "b.jpg"], "images": ["a.jpg", "b.jpg"],
            "imagePans": ["pan-left", "pan-right"], "attractionNarration": "x", **kw}


def test_the_ticks_are_read_per_photo_and_padded_to_the_photo_count():
    assert _resolve_attraction_ai(_wp()) is None  # never set: the project-wide setting decides, as before
    assert _resolve_attraction_ai(_wp(imageAi=[True, False])) == [True, False]
    assert _resolve_attraction_ai(_wp(imageAi=[True])) == [True, False]  # a photo added after the tick: CPU


def test_comfyui_starts_only_when_a_photo_is_ticked():
    assert needs_wan([_wp()]) is True  # no ticks: the moving presets decide, unchanged
    assert needs_wan([_wp(imageAi=[True, False])]) is True
    assert needs_wan([_wp(imageAi=[False, False])]) is False  # every photo on the CPU: never start it
    # A still photo is never AI, so ticking it does not start ComfyUI.
    assert needs_wan([_wp(imagePans=["none", "none"], imageAi=[True, True])]) is False


def test_a_photos_own_tick_beats_the_project_setting():
    from services.vdoprocessing.img2vdo import AttractionVideoGenerator

    cpu_only = AttractionVideoGenerator._cpu_only
    both_off = type("C", (), {"get_settings": lambda self: {"photo_clip_engine": "cpu"}})()
    gen = type("G", (), {"config": both_off})()
    assert cpu_only(gen) is True  # the setting, with no per-photo choice
    assert cpu_only(gen, ai=True) is False  # ticked for AI
    assert cpu_only(gen, ai=False) is True
