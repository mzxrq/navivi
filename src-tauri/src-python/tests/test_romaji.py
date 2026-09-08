"""Unit tests for services/localization/romaji.py."""

import pytest

from services.localization import romaji
from services.localization.romaji import RomajiConverter


@pytest.fixture(autouse=True)
def _reset_romaji_class_state():
    """_kks/_glossary are cached class attributes — reset around every test
    so one test's monkeypatched glossary can't leak into the next."""
    original_kks = RomajiConverter._kks
    original_glossary = RomajiConverter._glossary
    yield
    RomajiConverter._kks = original_kks
    RomajiConverter._glossary = original_glossary


class TestToRomaji:
    def test_empty_text_returns_as_is(self):
        assert RomajiConverter.to_romaji("") == ""
        assert RomajiConverter.to_romaji(None) is None

    def test_converts_hiragana_to_romaji(self):
        result = RomajiConverter.to_romaji("ありがとう")
        assert "arigatou" in result.lower()

    def test_result_is_title_cased(self):
        result = RomajiConverter.to_romaji("おおさか")
        assert result == result.title()

    def test_glossary_term_is_substituted_verbatim(self):
        RomajiConverter._glossary = {"大阪市": "Osaka City"}
        result = RomajiConverter.to_romaji("大阪市に行く")
        assert "Osaka City" in result

    def test_glossary_prioritizes_romaji_key_over_en_key(self):
        RomajiConverter._glossary = {
            "京都": {"en": "Kyoto (en)", "romaji": "Kyoto"}
        }
        result = RomajiConverter.to_romaji("京都")
        assert "Kyoto" in result
        assert "(en)" not in result

    def test_glossary_falls_back_to_en_key_when_no_romaji_key(self):
        RomajiConverter._glossary = {"京都": {"en": "KyotoCity"}}
        result = RomajiConverter.to_romaji("京都")
        assert "KyotoCity" in result

    def test_pykakasi_unavailable_falls_back_to_original_text(self, monkeypatch):
        monkeypatch.setattr(romaji, "_PYKAKASI_AVAILABLE", False)
        RomajiConverter._kks = None
        original = "大阪市"
        assert RomajiConverter.to_romaji(original) == original


class TestLoadGlossary:
    def test_missing_glossary_file_returns_empty_dict(self, tmp_path):
        RomajiConverter._glossary = None
        result = RomajiConverter.load_glossary(tmp_path / "no_such_file.json")
        assert result == {}

    def test_existing_glossary_file_is_parsed(self, tmp_path):
        RomajiConverter._glossary = None
        glossary_path = tmp_path / "glossary.json"
        glossary_path.write_text('{"大阪": "Osaka"}', encoding="utf-8")
        result = RomajiConverter.load_glossary(glossary_path)
        assert result == {"大阪": "Osaka"}

    def test_glossary_is_cached_after_first_load(self, tmp_path):
        RomajiConverter._glossary = None
        glossary_path = tmp_path / "glossary.json"
        glossary_path.write_text('{"大阪": "Osaka"}', encoding="utf-8")
        RomajiConverter.load_glossary(glossary_path)
        # Even pointing at a different (nonexistent) path, the cached value wins.
        result = RomajiConverter.load_glossary(tmp_path / "other.json")
        assert result == {"大阪": "Osaka"}
