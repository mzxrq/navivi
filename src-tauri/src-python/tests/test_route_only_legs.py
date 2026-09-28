"""With attraction videos on, a leg speaks only its route text; the attraction
clip speaks the attraction text (it used to play twice, leg then clip)."""

import pytest

from services.vdoprocessing.videopipeline import audio_step
from services.vdoprocessing.videopipeline.narration_step import cued_script

WP = {
    "arrivingNarration": "駅から歩き始めて約5分。道の角に古い石の道しるべが見えてきます。",
    "attractionNarration": "こちらが加太の石標です。",
    "popup_image": ["1.jpg"],
}


@pytest.fixture
def route_only():
    audio_step.set_route_only_legs(True)
    yield
    audio_step.set_route_only_legs(False)


def test_leg_keeps_both_parts_by_default():
    assert "石標です" in audio_step.base_narration_script(WP)


def test_leg_drops_the_attraction_text_when_its_clip_speaks_it(route_only):
    script = audio_step.base_narration_script(WP)
    assert "石標です" not in script and "道しるべ" in script
    assert "石標です" not in (cued_script(WP) or "")


def test_no_photo_means_no_clip_so_the_leg_keeps_it(route_only):
    wp = dict(WP, popup_image=None)
    assert "石標です" in audio_step.base_narration_script(wp)


def test_old_audio_counts_as_the_full_text(tmp_path, route_only):
    audio = tmp_path / "leg.wav"
    audio.write_bytes(b"x" * 2048)
    full = audio_step.base_narration_script(WP, route_only=False)
    route = audio_step.base_narration_script(WP)
    assert audio_step._spoken_text_matches(audio, full, WP)
    assert not audio_step._spoken_text_matches(audio, route, WP)  # re-made route-only
    audio_step._spoken_text_path(audio).write_text(route, encoding="utf-8")
    assert audio_step._spoken_text_matches(audio, route, WP)
