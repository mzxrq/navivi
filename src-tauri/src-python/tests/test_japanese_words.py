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
