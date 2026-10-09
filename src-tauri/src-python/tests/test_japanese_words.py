import pytest

from services.localization import japanese_words as jw

pytestmark = pytest.mark.skipif(jw._tagger() is None, reason="fugashi/unidic-lite not installed")


def words(text):
    return {w["word"]: w["reading"] for w in jw.analyze_words(text)}


def test_a_verb_with_okurigana_stays_one_word_with_its_reading():
    found = words("透き通る海と、激しく打ち寄せる波が広がります。")
    assert found["透き通る"] == "すきとおる"
    assert found["打ち寄せる"] == "うちよせる"
    assert found["激しく"] == "はげしく"
    assert "透" not in found and "通" not in found


def test_te_and_ta_stay_on_the_verb():
    found = words("透き通った水に、輝いて見えました。")
    assert found["透き通った"] == "すきとおった"
    assert found["輝いて"] == "かがやいて"


def test_noun_runs_are_joined():
    found = words("三段壁の地下で、熊野水軍と源平合戦の話を聞きました。")
    assert "三段壁" in found
    assert "熊野水軍" in found
    assert "源平合戦" in found
    assert found["源平合戦"] == "げんぺいかっせん"


def test_words_without_kanji_and_repeats_are_left_out():
    result = jw.analyze_words("海と海、そしてきれいなそら。")
    assert [w["word"] for w in result] == ["海"]


def test_reading_of_a_phrase():
    assert jw.reading_of("透き通る") == "すきとおる"
    assert jw.reading_of("") is None


def test_to_hiragana_keeps_everything_else():
    assert jw.to_hiragana("スキトオル、ABC") == "すきとおる、ABC"


def test_dictionaries_merge_with_the_project_winning():
    from services.vdoprocessing.videopipeline.audio_step import merge_pronunciation

    merged = merge_pronunciation(
        [{"word": "三段壁", "reading": "さんだんへき"}, {"word": "白良浜", "reading": "しららはま"}],
        [{"word": "三段壁", "reading": "さんだんべき"}, {"word": "", "reading": "x"}],
    )
    assert {e["word"]: e["reading"] for e in merged} == {"三段壁": "さんだんべき", "白良浜": "しららはま"}
    assert merge_pronunciation(None, None) == []


def test_longer_words_are_replaced_first():
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary

    entries = [{"word": "三段", "reading": "さんだん"}, {"word": "三段壁", "reading": "さんだんべき"}]
    assert apply_pronunciation_dictionary("三段壁と三段", entries) == "サンダンベキとサンダン"


def test_several_scripts_in_one_scan_list_each_word_once():
    result = jw.analyze_words("三段壁へ向かいます。\n三段壁の洞窟です。\n白良浜に着きました。")
    names = [w["word"] for w in result]
    assert names.count("三段壁") == 1
    assert names.index("三段壁") < names.index("白良浜")


def test_auto_flagged_entries_are_applied_like_any_other():
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary, merge_pronunciation

    entries = merge_pronunciation([], [{"word": "三段壁", "reading": "さんだんべき", "auto": True}])
    assert entries == [{"word": "三段壁", "reading": "さんだんべき", "auto": True}]
    assert apply_pronunciation_dictionary("三段壁へ", entries) == "サンダンベキへ"


def test_every_dictionary_word_is_spelled_out_by_default():
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary

    entries = [{"word": "慈眼院", "reading": "じげんいん", "auto": True}, {"word": "西念寺", "reading": "さいねんじ", "auto": True}]
    assert apply_pronunciation_dictionary("慈眼院と西念寺", entries) == "ジゲン院とサイネン寺"


def test_an_auto_place_name_the_analyser_reads_right_keeps_its_kanji_and_is_checked(monkeypatch):
    from services import tuning
    from services.tts import name_check
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary

    monkeypatch.setattr(tuning, "TTS_KANJI_FIRST", True)
    entries = [{"word": "三輪神社", "reading": "みわじんじゃ", "auto": True}, {"word": "札立山", "reading": "ふだたてやま", "auto": True}]
    text = apply_pronunciation_dictionary("三輪神社から札立山へ", entries)
    assert text == "三輪神社からフダタテヤマへ"
    assert ("三輪神社", "みわじんじゃ") in name_check.expected_names(text)
    assert name_check.spell_out(text, ["三輪神社"]) == "ミワ神社からフダタテヤマへ"


def test_a_manual_word_is_always_replaced_and_katakana_or_mixed_readings_pass_through():
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary

    entries = [{"word": "東京", "reading": "とうきょう"}, {"word": "白良浜", "reading": "シララハマ"}, {"word": "1号", "reading": "いちごう線"}]
    assert apply_pronunciation_dictionary("東京と白良浜と1号", entries) == "トウキョウとシララハマといちごう線"


def test_to_katakana_keeps_everything_else():
    assert jw.to_katakana("すきとおる、ABC") == "スキトオル、ABC"


def test_each_part_of_a_bracketed_name_is_looked_up_on_its_own(monkeypatch):
    from services.localization import jmnedict

    known = {"西念寺": ["さいねんじ"], "孝子駅": ["きょうしえき"]}
    monkeypatch.setattr(jmnedict, "readings", lambda name: list(known.get(name, [])))
    words = jw.analyze_place_words("西念寺（二ノ宿観音堂）から孝子駅 (GOAL)へ。", ["西念寺（二ノ宿観音堂）", "孝子駅 (GOAL)"])
    readings = {w["word"]: w["reading"] for w in words}
    assert readings["西念寺（二ノ宿観音堂）"].startswith("さいねんじ（")
    assert readings["孝子駅 (GOAL)"] == "きょうしえき (GOAL)"


def test_ato_after_a_building_reads_ato_but_iseki_stays():
    assert jw.ruins_reading("神福寺跡", "しんぷくじせき") == "しんぷくじあと"
    assert jw.ruins_reading("大坂城跡", "おおさかじょうせき") == "おおさかじょうあと"
    assert jw.ruins_reading("遺跡", "いせき") == "いせき"
    assert jw.ruins_reading("古墳遺跡", "こふんいせき") == "こふんいせき"


def test_a_ruins_name_in_a_sentence_reads_ato():
    words = {w["word"]: w["reading"] for w in jw.analyze_place_words("葛城第二経塚（神福寺跡）へ。", ["葛城第二経塚（神福寺跡）"])}
    assert words["葛城第二経塚（神福寺跡）"].endswith("（しんぷくじあと）")
    assert words["神福寺跡"] == "しんぷくじあと"


def test_an_auto_ruins_name_is_always_given_to_the_voice_as_its_reading():
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary

    entry = {"word": "神福寺跡", "reading": "しんぷくじあと", "auto": True}
    assert apply_pronunciation_dictionary("神福寺跡へ。", [entry]) == "シンプクジアトへ。"


def test_spoken_kana_spells_out_kanji_words_as_they_are_said():
    assert jw.spoken_kana("雰囲気漂う空間です。") == "フンイキタダヨウクーカンです。"


def test_spoken_kana_keeps_a_counter_after_a_number():
    assert jw.spoken_kana("1分ほど") == "1分ほど"


def test_spoken_kana_reads_ho_for_a_step():
    assert jw.spoken_kana("歩を進める") == "ホをススメル"


def test_an_ending_with_one_reading_stays_in_kanji():
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary

    entries = [{"word": "猿坂峠", "reading": "さるさかとうげ"}, {"word": "三輪神社", "reading": "みわじんじゃ"}]
    assert apply_pronunciation_dictionary("猿坂峠から三輪神社へ", entries) == "サルサカ峠からミワ神社へ"
