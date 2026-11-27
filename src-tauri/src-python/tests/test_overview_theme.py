"""The totals card's design is a theme (docs/OVERVIEW_RULES.md 8.16); only "current" exists, today's look."""
import pytest

from services import tuning
from services.vdoprocessing.videopipeline.animator_config import summary_card_style


@pytest.mark.parametrize("theme", [None, "current", "no-such-theme"])
@pytest.mark.parametrize("style", ["glass", "taskbar", "columns", "circles", "stacked", None])
def test_current_and_unknown_themes_give_todays_card(theme, style):
    settings = {k: v for k, v in (("overview_theme", theme), ("summary_card_style", style)) if v}
    assert summary_card_style(settings) == (style or tuning.DEFAULT_SUMMARY_CARD_STYLE)


def test_a_themes_card_style_beats_the_projects(monkeypatch):
    monkeypatch.setitem(tuning.OVERVIEW_THEMES, "night", {"card_style": "glass"})
    assert summary_card_style({"overview_theme": "night", "summary_card_style": "columns"}) == "glass"
    assert tuning.overview_theme("night") == {"card_style": "glass"} and tuning.overview_theme("gone") == {}
