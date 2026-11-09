from services.vdoprocessing.videopipeline.audio_step import no_attraction, no_narration_stop


def test_a_stop_left_without_narration_gets_no_attraction_clip():
    quiet = {"label": "近鉄御所駅", "attractionNarration": "", "videos": []}
    assert no_narration_stop(quiet) and no_attraction(quiet)


def test_narration_or_own_video_keeps_the_clip():
    assert not no_attraction({"label": "a", "attractionNarration": "ここは駅です。"})
    assert not no_narration_stop({"label": "a", "attractionNarration": "", "videos": ["clip.mp4"]})
    assert not no_narration_stop({"label": "old config without the field"})
