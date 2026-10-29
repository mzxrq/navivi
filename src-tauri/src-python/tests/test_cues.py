

def test_open_close_cues_time_the_intro_heading():
    from services import tuning
    from services.localization.cues import cue_tags, clean_text
    from services.vdoprocessing.videopipeline.intro_step import cued_heading

    script = "{open}友ヶ島へ。{close}旅をはじめよう。"
    assert cue_tags(script) == ["open", "close"] and clean_text(script) == "友ヶ島へ。旅をはじめよう。"
    lead = tuning.INTRO_VOICE_LEAD_SECONDS
    item = cued_heading({"title": {"text": "T"}}, {"open": 1.0, "close": 3.0})
    assert item["start"] == round(lead + 1.0, 3) and item["end"] == round(lead + 3.0, 3)
    assert cued_heading({"title": {"text": "T"}}, {"start": 2.0}) == {"title": {"text": "T"}}


def test_photo_cues_choose_the_intro_photos():
    from services import tuning
    from services.localization.cues import clean_text, cue_tags
    from services.vdoprocessing.introclip import cued_layout, scene_starts
    from services.vdoprocessing.videopipeline.intro_step import photo_cuts

    script = "祈りの道。{photo:友ヶ島}友ヶ島へ。{photo:加太}加太から。"
    assert cue_tags(script) == ["photo1:友ヶ島", "photo2:加太"] and "{" not in clean_text(script)
    wps = [{"label": "加太駅", "popup_image": ["a.jpg"]}, {"label": "友ヶ島 神島", "popup_image": "t.jpg"}]
    lead = tuning.INTRO_VOICE_LEAD_SECONDS
    cuts = photo_cuts({"photo1:友ヶ島": 3.0, "photo2:加太": 6.0, "photo3:どこか": 7.0}, wps)
    assert cuts == [(lead + 3.0, "t.jpg"), (lead + 6.0, "a.jpg")]
    layout = cued_layout(12.0, cuts)
    assert [p for p, _ in layout] == [None, "t.jpg", "a.jpg"]
    secs = [s for _, s in layout]
    assert scene_starts(secs, tuning.INTRO_CROSSFADE_SECONDS) == [0.0, lead + 3.0, lead + 6.0]
    assert abs(sum(secs) - 2 * tuning.INTRO_CROSSFADE_SECONDS - 12.0) < 1e-6


def test_photo_cue_picks_the_scene_footage(tmp_path):
    from services.vdoprocessing.introclip import scene_overrides

    clip = tmp_path / "04_attraction_01_友ヶ島_神島.mp4"
    clip.write_bytes(b"x")
    wps = [{"popup_image": "a.jpg"}, {"popup_image": ["t.jpg"]}, {"popup_image": "k.jpg"}]
    scenes = [{"seconds": 5.0}, {"seconds": 5.0}, {"seconds": 5.0}]
    # scene 2 starts at 5 - crossfade; a cue at 0.5 picks scene 1's footage, one at 6.0 scene 2's
    picks = scene_overrides(scenes, [(0.5, "t.jpg"), (1.0, "a.jpg"), (6.0, "k.jpg")], wps, [str(clip)])
    assert picks == {0: str(clip), 1: "k.jpg"}


def test_one_scene_cue_in_a_three_scene_intro_is_used():
    from services import tuning
    from services.vdoprocessing.introclip import scene_starts, styled_scenes

    scenes = styled_scenes("cinematic", 30.0, [14.0])
    starts = scene_starts([s["seconds"] for s in scenes], tuning.INTRO_CROSSFADE_SECONDS)
    assert len(scenes) == 3 and abs(starts[1] - (14.0 - tuning.INTRO_CROSSFADE_SECONDS / 2)) < 1e-6
    assert starts[1] < starts[2] < 30.0
