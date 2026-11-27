"""Offline tests for the overview's stop-and-describe cues ({n} ... {go})."""

import json
import re

import pytest

from services.localization.cues import Cue, clean_text, cue_tags, cue_times, strip_cues
from services.localization.overview_cues import auto_tag_overview, name_variants

# A script whose {start} the writer typed: the opening before it plays over the intro and names places too.
OPENING = "{photo:加太淡嶋神社}加太淡嶋神社で知られる町です。常行寺もあります。"


def test_no_number_lands_before_the_writers_own_start():
    text = OPENING + "{start}駅を出発します。常行寺には大木があります。加太淡嶋神社へ着きます。"

    tagged = auto_tag_overview(text, ["常行寺", "加太淡嶋神社"])

    assert tagged.startswith(OPENING + "{start}")  # the opening is untouched, and there is one {start}
    assert tagged.count("{start}") == 1
    assert "{1}常行寺には" in tagged and "{2}加太淡嶋神社へ" in tagged


def test_a_stop_named_right_after_the_start_is_tagged_there():
    tagged = auto_tag_overview(OPENING + "{start}常行寺から歩きます。", ["常行寺"])

    assert tagged == OPENING + "{start}{1}常行寺から歩きます。"


def test_a_course_script_with_its_own_start_numbers_each_name_in_the_route_sentences():
    text = OPENING + "{start}これが全体のルートです。{route}常行寺を過ぎて加太淡嶋神社へ向かいます。"

    tagged = auto_tag_overview(text, ["常行寺", "加太淡嶋神社"])

    assert tagged == OPENING + "{start}これが全体のルートです。{route}{1}常行寺を過ぎて{2}加太淡嶋神社へ向かいます。{go}"


def test_numbers_an_earlier_version_saved_in_the_opening_are_placed_again(tmp_path):
    import json

    from services.vdoprocessing.videopipeline.narration_step import CueStore, add_overview_cues

    base = OPENING + "{start}常行寺から歩きます。"
    config = tmp_path / "job_config.json"
    places = [{"label": name, "lat": 34.0 + i / 100, "lng": 135.0} for i, name in enumerate(["駅", "常行寺", "港"])]
    config.write_text(json.dumps({"overview_narration": base, "waypoints": places}), encoding="utf-8")
    store = CueStore(tmp_path)
    store.put_text("overview", base, "{1}" + base)  # as saved before the fix
    store.save()

    assert add_overview_cues(str(config))

    assert CueStore(tmp_path).cued_text("overview", base) == OPENING + "{start}{1}常行寺から歩きます。"
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


COURSE_SCRIPT = (
    "友ヶ島は四つの島です。これが全体のルートです。島では、砲台跡やタカノス山をめぐります。"
    "黒色で示した地点は、追加の見どころです。赤色で示した地点は、立ち入れません。"
)
COURSE_LABELS = ["砲台跡", "タカノス山"]
KIND_TAG = {"n": r"\{\d+\}", "go": r"\{go\}", "start": r"\{start\}", "extras": r"\{extras\}", "closed": r"\{closed\}"}


@pytest.mark.parametrize("kind", list(KIND_TAG))
def test_a_cue_kind_switched_off_is_not_added(kind):
    full = auto_tag_overview(COURSE_SCRIPT, COURSE_LABELS)
    assert all(re.search(tag, full) for tag in KIND_TAG.values())  # every kind is there to switch off
    tagged = auto_tag_overview(COURSE_SCRIPT, COURSE_LABELS, skip=frozenset({kind}))
    assert tagged == re.sub(KIND_TAG[kind], "", full)


@pytest.mark.parametrize("kind", list(KIND_TAG))
def test_a_typed_cue_stays_when_its_kind_is_off(kind):
    typed = {"n": "{1}", "go": "{go}", "start": "{start}", "extras": "{extras}", "closed": "{closed}"}[kind]
    tagged = auto_tag_overview(typed + COURSE_SCRIPT, COURSE_LABELS, skip=frozenset({kind}))
    assert typed in tagged


def _stored_tags(config, tmp_path):
    return cue_tags(overview_tagged_script(json.loads(config.read_text(encoding="utf-8")), tmp_path))


def _set(config, **settings):
    project = json.loads(config.read_text(encoding="utf-8"))
    project["settings"] = settings
    config.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")


class TestSwitches:
    def test_a_switch_turned_off_then_on_again_retags(self, tmp_path):
        config = _project(tmp_path, {"auto_cue_go": False})
        add_overview_cues(str(config))
        assert _stored_tags(config, tmp_path) == ["1", "2", "3"]
        _set(config)
        assert add_overview_cues(str(config)) is True
        assert _stored_tags(config, tmp_path) == ["1", "go1", "2", "go2", "3"]
        _set(config, auto_cue_go=False)
        assert add_overview_cues(str(config)) is True
        assert _stored_tags(config, tmp_path) == ["1", "2", "3"]

    def test_the_master_off_drops_the_tags_it_added(self, tmp_path):
        config = _project(tmp_path, {})
        add_overview_cues(str(config))
        _set(config, auto_overview_cues=False)
        add_overview_cues(str(config))
        assert _stored_tags(config, tmp_path) == []
        assert add_overview_cues(str(config)) is False

    @pytest.mark.parametrize("on", [True, False])
    def test_the_scene_switch(self, tmp_path, on):
        config = _project(tmp_path, {"intro_style": "cinematic", "auto_cue_scene": on})
        project = json.loads(config.read_text(encoding="utf-8"))
        project["overview_narration"] = "一文です。二文です。三文です。{start}" + SCRIPT
        config.write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
        add_overview_cues(str(config))
        assert ("{scene}" in overview_tagged_script(project, tmp_path)) is on


def test_cue_numbers_that_name_the_wrong_stop_are_reported():
    from services.localization.overview_cues import cue_name_mismatches

    labels = ["石標", "加太淡嶋神社", "友ヶ島 野奈浦桟橋 (Return)"]
    assert cue_name_mismatches("{1}加太淡嶋神社へ。{go}", labels) == [(1, "加太淡嶋神社", "石標")]
    assert cue_name_mismatches("{1}石標、{2}加太淡嶋神社、{3}友ヶ島 野奈浦桟橋へ。", labels) == []
    assert cue_name_mismatches("{4}どこか", labels) == [(4, "どこか", "")]
