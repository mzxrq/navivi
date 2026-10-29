

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
