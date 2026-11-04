from services import tuning


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
    cued = scene_overrides(scenes, [(0.5, "t.jpg"), (3.0, "a.jpg"), (6.0, "k.jpg")], wps, [str(clip)])
    cf = tuning.INTRO_CROSSFADE_SECONDS
    assert cued == {0: [(0.5, str(clip)), (3.0, "a.jpg")], 1: [(6.0 - (5.0 - cf), "k.jpg")]}


def test_two_photo_cues_in_one_scene_play_one_after_the_other():
    from services.vdoprocessing.introclip import cued_shots, scene_starts

    cf = tuning.INTRO_CROSSFADE_SECONDS
    shots = cued_shots(8.0, [(0.5, "a"), (4.0, "b")], cf)
    assert [s for s, _ in shots] == ["a", "b"]
    # b starts crossfading in exactly at its cue, and the two still fill the scene
    assert scene_starts([d for _, d in shots], cf) == [0.0, 4.0]
    assert abs(sum(d for _, d in shots) - cf - 8.0) < 1e-6
    # a cue too close to the previous one, or to the scene's end, is dropped
    assert [s for s, _ in cued_shots(8.0, [(0.0, "a"), (0.2, "b"), (7.9, "c")], cf)] == ["a"]


def test_one_scene_cue_in_a_three_scene_intro_is_used():
    from services import tuning
    from services.vdoprocessing.introclip import scene_starts, styled_scenes

    scenes = styled_scenes("cinematic", 30.0, [14.0])
    starts = scene_starts([s["seconds"] for s in scenes], tuning.INTRO_CROSSFADE_SECONDS)
    assert len(scenes) == 3 and abs(starts[1] - (14.0 - tuning.INTRO_CROSSFADE_SECONDS / 2)) < 1e-6
    assert starts[1] < starts[2] < 30.0


def test_a_two_photo_place_plays_each_photo_on_its_own_in_the_intro(tmp_path):
    import json

    from services.vdoprocessing.introclip import photo_clips, scene_overrides

    clip = tmp_path / "04_attraction_01_郵便名柄館.mp4"
    clip.write_bytes(b"x")
    (tmp_path / "_inputs").mkdir()
    (tmp_path / "_inputs" / "04_attraction_01_郵便名柄館.json").write_text(json.dumps({"keys": ["aaa", "bbb"]}))
    for key in ("aaa", "bbb"):
        (tmp_path / f"raw_04_attraction_01_郵便名柄館_{key}.mp4").write_bytes(b"x")
    singles = photo_clips(str(clip))
    assert [s.rsplit("_", 1)[-1] for s in singles] == ["aaa.mp4", "bbb.mp4"]
    wps = [{"popup_image": "s.jpg"}, {"popup_image": ["one.jpg", "two.jpg"]}]
    cued = scene_overrides([{"seconds": 9.0}], [(0.5, "two.jpg")], wps, [str(clip)])
    assert cued == {0: [(0.5, singles[1])]}  # the second photo's own clip, not the one that swaps partway


def test_no_intro_shot_is_shorter_than_the_minimum():
    from services.vdoprocessing.introclip import cued_layout, cued_shots, plan_shots

    cf, least = tuning.INTRO_CROSSFADE_SECONDS, tuning.INTRO_MIN_SHOT_SECONDS
    assert [s for s, _ in cued_shots(9.0, [(0.0, "a"), (1.8, "b"), (5.0, "c")], cf)] == ["a", "c"]
    shots = plan_shots(6.0, "main", ["p1", "p2", "p3", "p4"], {"main": 0.5, "p1": 0.5, "p2": 0.5, "p3": 0.5, "p4": 0.5}, cf, 2)
    assert (6.0 + (len(shots) - 1) * cf) / len(shots) >= least
    assert all(sec >= least for _, sec in cued_layout(12.0, [(0.0, "a"), (1.0, "b"), (6.0, "c")]))
