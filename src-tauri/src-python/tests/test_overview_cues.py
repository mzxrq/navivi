"""Offline tests for the overview's stop-and-describe cues ({n} ... {go})."""

import json

from services.localization.cues import Cue, clean_text, cue_tags, cue_times, strip_cues
from services.localization.overview_cues import auto_tag_overview, name_variants
from services.vdoprocessing.videopipeline.audio_step import overview_tagged_script
from services.vdoprocessing.videopipeline.narration_step import add_overview_cues

SCRIPT = (
    "皆さん、こんにちは。加太から旅が始まります。\n"
    "加太駅は小さな駅です。レトロな駅舎が人気です。次は、町を歩いて常行寺へ向かいます。\n"
    "常行寺は静かなお寺です。境内には古い石標があります。ここから春日神社へ進みます。\n"
    "加太春日神社は町の氏神です。"
)
LABELS = ["加太駅", "常行寺", "加太春日神社"]


class TestGoTag:
    def test_go_belongs_to_the_stop_before_it(self):
        clean, cues = strip_cues("あ{1}いい。{go}うう{2}ええ。{go}お")
        assert clean == "あいい。ううええ。お"
        assert cues == [Cue("1", 1), Cue("go1", 4), Cue("2", 6), Cue("go2", 9)]

    def test_go_before_any_stop_is_ignored(self):
        assert cue_tags("{go}あ{1}い") == ["1"]

    def test_go_is_never_spoken(self):
        assert clean_text("あ。{go}い") == "あ。い"

    def test_go_snaps_to_where_the_voice_starts_again(self):
        clean, cues = strip_cues("ああああ{1}ああ。{go}いいいい")
        times = cue_times(cues, clean, 10.0, [{"start": 5.6, "end": 6.4}])
        assert times["go1"] == 6.4

    def test_go_far_from_any_pause_keeps_its_estimate(self):
        pauses = [{"start": 1.0, "end": 1.2}]
        clean, cues = strip_cues("ああああ{1}ああ{go}いいいい")
        plain_clean, plain_cues = strip_cues("ああああ{1}ああ{2}いいいい")
        plain = cue_times(plain_cues, plain_clean, 10.0, pauses)
        assert cue_times(cues, clean, 10.0, pauses)["go1"] == plain["2"]


class TestAutoTag:
    def test_names_and_transitions_are_tagged_without_changing_a_word(self):
        tagged = auto_tag_overview(SCRIPT, LABELS)
        assert clean_text(tagged) == SCRIPT
        assert cue_tags(tagged) == ["1", "go1", "2", "go2", "3"]
        assert "{1}加太駅は" in tagged
        assert "{go}次は、" in tagged
        assert "{3}加太春日神社は" in tagged

    def test_a_short_form_of_the_name_is_found(self):
        assert "加太春日" in name_variants("加太春日神社")
        tagged = auto_tag_overview("さあ出発。加太春日の森です。", ["加太春日神社"])
        assert tagged == "さあ出発。{1}加太春日の森です。"

    def test_stops_are_found_in_route_order(self):
        # 常行寺 is mentioned in passing before 加太駅 is described: stop 2 is
        # its later sentence, not the earlier mention.
        text = "常行寺まで歩きます。加太駅は小さな駅です。常行寺は静かです。"
        tagged = auto_tag_overview(text, ["加太駅", "常行寺"])
        assert tagged == "常行寺まで歩きます。{1}加太駅は小さな駅です。{2}常行寺は静かです。"

    def test_the_users_own_stops_are_kept_and_get_a_go(self):
        text = "{1}ここは駅です。次は寺へ向かいます。{2}寺です。"
        assert auto_tag_overview(text, ["X", "Y"]) == "{1}ここは駅です。{go}次は寺へ向かいます。{2}寺です。"

    def test_a_fully_tagged_script_is_left_alone(self):
        text = "{1}駅です。{go}次へ。{2}寺です。"
        assert auto_tag_overview(text, ["駅", "寺"]) == text

    def test_nothing_found_leaves_the_script_as_is(self):
        assert auto_tag_overview("今日はいい天気です。", ["加太駅"]) == "今日はいい天気です。"


def _project(tmp_path, settings):
    waypoints = [{"label": "出発"}] + [{"label": l} for l in LABELS] + [{"label": "ゴール"}]
    config = tmp_path / "job_config.json"
    config.write_text(json.dumps(
        {"waypoints": waypoints, "overview_narration": SCRIPT, "settings": settings},
        ensure_ascii=False,
    ), encoding="utf-8")
    return config


class TestStored:
    def test_tags_are_stored_beside_the_config_and_read_back(self, tmp_path):
        config = _project(tmp_path, {"auto_overview_cues": True})
        assert add_overview_cues(str(config)) is True
        project = json.loads(config.read_text(encoding="utf-8"))
        assert project["overview_narration"] == SCRIPT  # job_config.json untouched
        assert cue_tags(overview_tagged_script(project, tmp_path)) == ["1", "go1", "2", "go2", "3"]
        assert add_overview_cues(str(config)) is False  # idempotent

    def test_an_edited_script_drops_the_stale_tags(self, tmp_path):
        config = _project(tmp_path, {"auto_overview_cues": True})
        add_overview_cues(str(config))
        edited = {"overview_narration": "別の台本です。"}
        assert overview_tagged_script(edited, tmp_path) == "別の台本です。"

    def test_on_by_default(self, tmp_path):
        config = _project(tmp_path, {})
        assert add_overview_cues(str(config)) is True

    def test_can_be_turned_off(self, tmp_path):
        config = _project(tmp_path, {"auto_overview_cues": False})
        assert add_overview_cues(str(config)) is False
        assert overview_tagged_script({"overview_narration": SCRIPT}, tmp_path) == SCRIPT
