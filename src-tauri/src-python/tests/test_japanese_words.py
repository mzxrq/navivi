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


def test_an_auto_word_the_analyser_already_reads_right_keeps_its_kanji():
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary

    entries = [{"word": "東京", "reading": "とうきょう", "auto": True}, {"word": "札立山", "reading": "ふだたてやま", "auto": True}]
    assert apply_pronunciation_dictionary("東京から札立山へ", entries) == "東京からフダタテヤマへ"


def test_a_manual_word_is_always_replaced_and_katakana_or_mixed_readings_pass_through():
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary

    entries = [{"word": "東京", "reading": "とうきょう"}, {"word": "白良浜", "reading": "シララハマ"}, {"word": "1号", "reading": "いちごう線"}]
    assert apply_pronunciation_dictionary("東京と白良浜と1号", entries) == "トウキョウとシララハマといちごう線"


def test_to_katakana_keeps_everything_else():
    assert jw.to_katakana("すきとおる、ABC") == "スキトオル、ABC"
