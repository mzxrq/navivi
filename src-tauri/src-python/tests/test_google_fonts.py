import pytest

from services.localization import fonts, google_fonts

FAMILIES = [
    {"family": "Zen Maru Gothic", "category": "Sans Serif", "subsets": ["japanese", "latin"], "popularity": 20, "primaryScript": "Jpan", "fonts": {"400": {}, "700": {}}},
    {"family": "Roboto", "category": "Sans Serif", "subsets": ["latin", "cyrillic"], "popularity": 1, "primaryScript": "", "fonts": {"400": {}, "700": {}}},
    {"family": "Lobster", "category": "Display", "subsets": ["latin"], "popularity": 50, "primaryScript": "", "fonts": {"400": {}}},
    {"family": "Noto Sans Devanagari", "category": "Sans Serif", "subsets": ["devanagari", "latin"], "popularity": 5, "primaryScript": "Deva", "fonts": {"400": {}}},
    {"family": "Noto Sans KR", "category": "Sans Serif", "subsets": ["korean", "latin"], "popularity": 3, "primaryScript": "Kore", "fonts": {"400": {}}},
]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(google_fonts, "_families", lambda: FAMILIES)
    monkeypatch.setattr(fonts, "downloaded_font_families", lambda: ["Roboto"])


def test_catalog_keeps_each_language_s_own_fonts_most_popular_first():
    assert [f["family"] for f in google_fonts.catalog("ja")] == ["Zen Maru Gothic"]
    en = google_fonts.catalog("en")
    assert [f["family"] for f in en] == ["Roboto", "Lobster"]
    assert en[0]["installed"] and not en[1]["installed"]
    assert not en[1]["bold"]
    assert google_fonts.catalog("xx") == []


def test_install_downloads_each_weight_and_registers_it(monkeypatch, tmp_path):
    css = (
        "@font-face { font-family: 'Zen Maru Gothic'; font-weight: 400; src: url(https://fonts.gstatic.com/s/zen/r.ttf) format('truetype'); }\n"
        "@font-face { font-family: 'Zen Maru Gothic'; font-weight: 700; src: url(https://fonts.gstatic.com/s/zen/b.ttf) format('truetype'); }\n"
    )
    fetched, registered = [], []

    def fake_get(url, user_agent="Mozilla/5.0"):
        fetched.append(url)
        return css.encode() if "googleapis" in url else b"ttf:" + url.encode()

    monkeypatch.setattr(google_fonts, "_get", fake_get)
    monkeypatch.setattr(google_fonts, "_user_font_dir", lambda: tmp_path)
    monkeypatch.setattr(google_fonts, "_register", lambda path, display: registered.append((path.name, display)))

    files = google_fonts.install("Zen Maru Gothic")
    assert [p.split("\\")[-1].split("/")[-1] for p in files] == ["Zen-Maru-Gothic-Regular.ttf", "Zen-Maru-Gothic-Bold.ttf"]
    assert (tmp_path / "Zen-Maru-Gothic-Bold.ttf").read_bytes() == b"ttf:https://fonts.gstatic.com/s/zen/b.ttf"
    assert registered == [("Zen-Maru-Gothic-Regular.ttf", "Zen Maru Gothic"), ("Zen-Maru-Gothic-Bold.ttf", "Zen Maru Gothic Bold")]
    assert "family=Zen+Maru+Gothic:wght@400;700" in fetched[0]


def test_install_refuses_a_name_that_is_not_a_family():
    with pytest.raises(ValueError):
        google_fonts.install("../evil")
