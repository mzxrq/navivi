"""Offline tests for narration cues and the audio-first walk plan (no TTS, no render)."""

import json

import pytest

from services.localization.cues import Cue, clean_text, cue_tags, cue_times, strip_cues
from services.vdoprocessing.cliptiming import read_audio_offset, write_audio_offset
from services.vdoprocessing.videopipeline import audio_step
from services.vdoprocessing.videopipeline.narration_step import (
    MIN_WALK_SECONDS,
    TAIL_SECONDS,
    CueStore,
    add_default_cues,
    cued_script,
    leg_walk_plan,
    record_cue_times,
)
from services.vdoprocessing.videopipeline.subtitle_step import shift_srt

ARRIVING = "淡嶋神社に近づいてきました。参道を進んでいきます。"
ATTRACTION = "ここは人形供養で知られる神社です。境内には人形が並びます。"


class TestCues:
    def test_strip_removes_tags_and_records_positions(self):
        clean, cues = strip_cues("{start}あい{arrive}うえ{end}")
        assert clean == "あいうえ"
        assert cues == [Cue("start", 0), Cue("arrive", 2), Cue("end", 4)]

    def test_numbered_cues_and_unknown_braces(self):
        assert cue_tags("{2}あ{10}い") == ["2", "10"]
        assert clean_text("あ{foo}い") == "あ{foo}い"

    def test_cue_times_skip_pauses(self):
        clean, cues = strip_cues("あああああ{arrive}ううううう")
        # 10 chars over 10s with a 2s pause at 3-5 -> 8s of speech; halfway
        # through the speech (4s) is 2s after the pause ends.
        times = cue_times(cues, clean, 10.0, [{"start": 3.0, "end": 5.0}])
        assert abs(times["arrive"] - 6.0) < 0.01

    def test_no_cues(self):
        assert cue_times([], "あ", 1.0) == {}


class TestDefaultCues:
    def test_placement_follows_the_project_convention(self):
        cued = cued_script({"arrivingNarration": ARRIVING, "attractionNarration": ATTRACTION})
        assert cue_tags(cued) == ["start", "arrive", "end"]
        assert clean_text(cued) == ARRIVING + ATTRACTION

    def test_users_own_cues_are_kept(self):
        assert cued_script({"arrivingNarration": "あ。{end}い。"}) == "あ。{end}い。"

    def test_stored_and_spoken_without_touching_job_config(self, tmp_path):
        config = tmp_path / "job_config.json"
        wp = {"id": "b", "label": "神社", "arrivingNarration": ARRIVING, "attractionNarration": ATTRACTION}
        config.write_text(json.dumps({"waypoints": [wp], "settings": {"auto_narration_cues": True}}), encoding="utf-8")
        assert add_default_cues(str(config)) == 1
        waypoints = json.loads(config.read_text(encoding="utf-8"))["waypoints"]
        audio_step.apply_cued_scripts(waypoints, tmp_path)
        assert cue_tags(audio_step.raw_narration_script(waypoints[0])) == ["start", "arrive", "end"]
        assert audio_step._resolve_narration_script(waypoints[0]) == ARRIVING + ATTRACTION
        assert cue_tags(json.loads(config.read_text(encoding="utf-8"))["waypoints"][0]["arrivingNarration"]) == []
        assert add_default_cues(str(config)) == 0  # idempotent

    def test_edited_script_drops_the_stale_cued_text(self, tmp_path):
        store = CueStore(tmp_path)
        store.put_text("b", "old script", "old {end}script")
        assert store.cued_text("b", "old script") == "old {end}script"
        assert store.cued_text("b", "edited") is None

    def test_off_unless_asked_for(self, tmp_path):
        config = tmp_path / "job_config.json"
        wp = {"id": "b", "arrivingNarration": ARRIVING, "attractionNarration": ATTRACTION}
        config.write_text(json.dumps({"waypoints": [wp], "settings": {}}), encoding="utf-8")
        assert add_default_cues(str(config)) == 0


class TestWalkPlan:
    def test_cue_times_are_recorded_from_audio(self, tmp_path):
        config = tmp_path / "job_config.json"
        wp = {"id": "b", "arrivingNarration": ARRIVING, "attractionNarration": ATTRACTION}
        config.write_text(json.dumps({"waypoints": [wp], "settings": {"auto_narration_cues": True}}), encoding="utf-8")
        add_default_cues(str(config))
        record_cue_times(str(config), {"audio_durations": [20.0], "audio_pauses": [[]]})
        assert set(CueStore(tmp_path).cue_times_for("b")) == {"start", "arrive", "end"}

    def test_the_end_cue_is_the_moment_it_must_have_arrived(self, tmp_path):
        store = CueStore(tmp_path)
        store.set_cue_times("b", {"start": 3.0, "arrive": 9.0, "end": 13.0})
        # Voice 30s, {start} at 3s -> 27s of voice from the walk's start; the walker
        # must have arrived by {end}, 10s after the walk starts. Its natural 8s is
        # inside "at most 3s early" (7-10s), so it keeps it and waits for the voice.
        walk, start, wait = leg_walk_plan(store, {"id": "b"}, 1, 30.0, natural_seconds=8.0)
        assert start == 3.0 and walk == 8.0 and wait == 27.0 - 8.0

    def test_arrival_is_held_to_the_cue_when_natural_pace_is_much_faster(self, tmp_path):
        store = CueStore(tmp_path)
        store.set_cue_times("b", {"end": 20.0})
        walk, _, wait = leg_walk_plan(store, {"id": "b"}, 1, 30.0, natural_seconds=6.0)
        assert walk == 17.0  # slowed so it is at most 3s early
        assert wait == 30.0 - 17.0

    def test_a_slow_natural_pace_is_sped_up_to_arrive_by_the_cue(self, tmp_path):
        store = CueStore(tmp_path)
        store.set_cue_times("b", {"end": 12.0})
        walk, _, wait = leg_walk_plan(store, {"id": "b"}, 1, 30.0, natural_seconds=25.0)
        assert walk == 12.0 and wait == 18.0

    def test_arrive_cue_is_used_when_there_is_no_end_cue(self, tmp_path):
        store = CueStore(tmp_path)
        store.set_cue_times("b", {"arrive": 14.0})
        assert leg_walk_plan(store, {"id": "b"}, 1, 30.0)[0] == 14.0

    def test_end_wins_over_arrive(self, tmp_path):
        store = CueStore(tmp_path)
        store.set_cue_times("b", {"arrive": 9.0, "end": 14.0})
        assert leg_walk_plan(store, {"id": "b"}, 1, 30.0)[0] == 14.0

    def test_cues_can_be_ignored(self, tmp_path):
        store = CueStore(tmp_path)
        store.set_cue_times("b", {"start": 3.0, "end": 14.0})
        assert leg_walk_plan(store, {"id": "b"}, 1, 20.0, use_cues=False) == (20.0 - TAIL_SECONDS, None, 0.0)

    def test_a_later_piece_ignores_the_start_cue(self, tmp_path):
        store = CueStore(tmp_path)
        store.set_cue_times("b", {"start": 3.0, "end": 13.0})
        walk, start, _ = leg_walk_plan(store, {"id": "b"}, 1, 30.0, ignore_start=True)
        assert start is None and walk == 13.0

    def test_arriving_late_is_sped_up_to_the_audio_length(self, tmp_path):
        # Natural pace 30s, but the voice is only 20s: walk 20s, no waiting.
        assert leg_walk_plan(CueStore(tmp_path), {"id": "b"}, 1, 20.0, natural_seconds=30.0) == (20.0, None, 0.0)

    def test_arriving_early_is_slowed_so_the_wait_is_at_most_3_seconds(self, tmp_path):
        # Natural pace 14s, voice 25s: it would wait 11s, so it is slowed to a
        # 22s walk and waits only the allowed 3s.
        walk, start, wait = leg_walk_plan(CueStore(tmp_path), {"id": "b"}, 1, 25.0, natural_seconds=14.0)
        assert (walk, start, wait) == (22.0, None, 3.0)

    def test_a_walk_already_within_the_limit_is_left_alone(self, tmp_path):
        assert leg_walk_plan(CueStore(tmp_path), {"id": "b"}, 1, 25.0, natural_seconds=23.0) == (23.0, None, 2.0)

    def test_the_limit_can_be_changed(self, tmp_path):
        assert leg_walk_plan(CueStore(tmp_path), {"id": "b"}, 1, 25.0, natural_seconds=14.0, max_wait_seconds=8.0) == (17.0, None, 8.0)

    def test_very_short_audio_keeps_a_minimum_walk(self, tmp_path):
        assert leg_walk_plan(CueStore(tmp_path), {"id": "b"}, 1, 3.0)[0] == MIN_WALK_SECONDS

    def test_no_audio_means_no_plan(self, tmp_path):
        assert leg_walk_plan(CueStore(tmp_path), {"id": "b"}, 1, 0.0) is None


def test_subtitles_and_export_delay_by_the_clip_opening(tmp_path):
    clip = tmp_path / "02_waypoint_01_x.mp4"
    write_audio_offset(str(clip), 6.6)
    # A padded/subtitled copy finds the original render's sidecar.
    assert read_audio_offset(str(tmp_path / "02_waypoint_01_x_padded_subtitled.mp4")) == 6.6
    srt = tmp_path / "a.srt"
    srt.write_text("1\n00:00:01,500 --> 00:00:59,900\nこんにちは\n", encoding="utf-8")
    assert "00:00:08,100 --> 00:01:06,500" in open(shift_srt(str(srt), 6.6), encoding="utf-8").read()
