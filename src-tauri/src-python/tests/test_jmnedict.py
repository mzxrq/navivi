import gzip

import pytest

from services.localization import jmnedict

SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE JMnedict [
<!ENTITY place "place name">
<!ENTITY station "railway station">
<!ENTITY surname "family or surname">
<!ENTITY unclass "unclassified name">
<!ENTITY company "company name">
]>
<JMnedict>
<entry><k_ele><keb>札立山</keb></k_ele><r_ele><reb>ふだたてやま</reb></r_ele><trans><name_type>&unclass;</name_type></trans></entry>
<entry><k_ele><keb>孝子</keb></k_ele><r_ele><reb>こうし</reb></r_ele><trans><name_type>&surname;</name_type></trans></entry>
<entry><k_ele><keb>孝子</keb></k_ele><r_ele><reb>きょうし</reb></r_ele><trans><name_type>&place;</name_type></trans></entry>
<entry><k_ele><keb>孝子駅</keb></k_ele><r_ele><reb>きょうしえき</reb></r_ele><trans><name_type>&station;</name_type></trans></entry>
<entry><k_ele><keb>鳴滝不動</keb></k_ele><r_ele><reb>なるたきふどう</reb></r_ele><trans><name_type>&place;</name_type></trans></entry>
<entry><k_ele><keb>南海本線</keb></k_ele><r_ele><reb>なんかいほんせん</reb></r_ele><trans><name_type>&company;</name_type><name_type>&unclass;</name_type></trans></entry>
<entry><k_ele><keb>不動山</keb></k_ele><r_ele><reb>ふどうさん</reb></r_ele><r_ele><reb>ふどうやま</reb></r_ele><trans><name_type>&place;</name_type></trans></entry>
<entry><k_ele><keb>甲</keb><keb>乙</keb></k_ele><r_ele><reb>こう</reb><re_restr>甲</re_restr></r_ele><trans><name_type>&place;</name_type></trans></entry>
</JMnedict>
"""

MECAB = {"尊": "みこと", "孝子駅": "こうしえき"}


@pytest.fixture
def index(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIVI_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "JMnedict.xml.gz"
    with gzip.open(source, "wt", encoding="utf-8") as f:
        f.write(SAMPLE)
    jmnedict._index.cache_clear()
    jmnedict.ensure_index(download=lambda url, target: target.write_bytes(source.read_bytes()))
    yield
    jmnedict._index.cache_clear()


def test_only_place_like_names_are_kept(index):
    assert jmnedict.readings("孝子") == ["きょうし"]
    assert jmnedict.readings("札立山") == ["ふだたてやま"]


def test_a_reading_limited_to_one_spelling_stays_with_it(index):
    assert jmnedict.readings("甲") == ["こう"] and jmnedict.readings("乙") == []


def test_the_dictionary_wins_over_a_wrong_guess(index):
    assert jmnedict.place_reading("札立山", "さつたてやま", MECAB.get) == "ふだたてやま"


def test_the_guess_picks_between_several_readings(index):
    assert jmnedict.place_reading("不動山", "ふどうやま", MECAB.get) == "ふどうやま"
    assert jmnedict.place_reading("不動山", "ふどうざん", MECAB.get) == "ふどうさん"


def test_a_longer_name_is_built_from_names_it_knows(index):
    assert jmnedict.place_reading("南海本線孝子駅", "なんかいほんせんこうしえき", MECAB.get) == "なんかいほんせんきょうしえき"


def test_a_one_kanji_rest_takes_its_part_of_the_whole_guess(index):
    assert jmnedict.place_reading("鳴滝不動尊", "なるたきふどうそん", MECAB.get) == "なるたきふどうそん"


def test_an_unknown_name_is_left_to_the_analyser(index):
    assert jmnedict.place_reading("高野山", "たかのやま", MECAB.get) is None


def test_without_the_dictionary_nothing_breaks_and_it_is_not_retried_at_once(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIVI_CACHE_DIR", str(tmp_path / "cache"))
    calls = []

    def offline(url, target):
        calls.append(url)
        raise OSError("no network")

    assert jmnedict.ensure_index(download=offline) is None
    assert jmnedict.ensure_index(download=offline) is None
    assert len(calls) == 1
