import pytest

from services.localization import japanese_words as jw


def test_project_place_names_in_the_text_come_first_in_order():
    text = "次は鳴滝不動尊へ。高仙寺から歩きます。"
    words = jw.analyze_place_words(text, ["高仙寺", "鳴滝不動尊", "札立山"])
    assert [w["word"] for w in words][:2] == ["鳴滝不動尊", "高仙寺"]
    assert all(w["reading"] for w in words)


def test_a_name_the_scripts_never_mention_is_left_out():
    words = jw.analyze_place_words("海がきれいです。", ["札立山"])
    assert "札立山" not in [w["word"] for w in words]


def test_kana_only_names_and_blanks_are_skipped():
    words = jw.analyze_place_words("バスていに着きました。", ["バスてい", "", "  "])
    assert words == [] or all(jw.has_kanji(w["word"]) for w in words)


@pytest.mark.skipif(jw._tagger() is None, reason="fugashi/unidic-lite not installed")
def test_common_words_are_not_place_names():
    words = [w["word"] for w in jw.analyze_place_words("美しい景色が広がる駅です。", [])]
    assert "美しい" not in words and "景色" not in words and "広がる" not in words
