"""On-video text language: the catalogs, the resolver, and that the drawn strings follow it."""

import json
import string

import numpy as np
import pytest

from services import tuning, video_text
from services.config.job_config import JobConfigManager
from services.mapfetcher.graphicengine import GraphicsEngine
from services.vdoprocessing import outrocard
from services.vdoprocessing.pydeckrecorder.pedestrian import _hud_text


def _flatten(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


def _fields(template):
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


def _config(tmp_path, settings=None, map_language="UNSET"):
    data = {"project_name": "t", "waypoints": []}
    if settings is not None:
        data["settings"] = settings
    if map_language != "UNSET":
        data["map_language"] = map_language
    path = tmp_path / "job_config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return JobConfigManager(str(path))


class TestCatalogs:
    def test_every_language_has_the_same_keys_and_placeholders(self):
        ja = dict(_flatten(video_text.labels_for("ja")))
        en = dict(_flatten(video_text.labels_for("en")))
        base_keys = lambda d: {k for k in d if not k.endswith("_one")}
        assert base_keys(ja) == base_keys(en)
        for key in base_keys(ja):
            if isinstance(ja[key], str) and isinstance(en[key], str):
                assert _fields(ja[key]) == _fields(en[key]), key

    def test_english_has_no_japanese_characters(self):
        for key, value in _flatten(video_text.labels_for("en")):
            assert all(ord(c) < 0x3000 or ord(c) > 0xFFEF for c in str(value)), key

    def test_japanese_is_what_the_renderer_always_drew(self):
        ja = video_text.labels_for("ja")
        assert ja["start_prefix"] == "出発: " and ja["stop_prefix"] == "到着: "
        assert ja["mode_duration_label"]["walking"] == "歩く時間"
        assert ja["soon_banner"].format(dest="X") == "まもなく X"
        assert ja["en_route_banner"].format(dest="X", suffix="") == "X へ"
        assert tuning.OUTRO_SUBTITLE_TEMPLATE.format(count=5) == "訪れた5か所"
        assert tuning.PIPELINE_LABELS == ja

    def test_unknown_language_falls_back_to_japanese_and_copies_are_independent(self):
        assert video_text.labels_for("xx") == video_text.labels_for("ja")
        video_text.labels_for("en")["mode_name"]["walking"] = "changed"
        assert video_text.labels_for("en")["mode_name"]["walking"] == "Walk"

    def test_plural(self):
        en = video_text.labels_for("en")
        assert video_text.plural(en, "place_count", 1, n=1) == "1 place"
        assert video_text.plural(en, "place_count", 5, n=5) == "5 places"
        ja = video_text.labels_for("ja")
        assert video_text.plural(ja, "place_count", 1, n=1) == "1 か所"


class TestResolver:
    @pytest.mark.parametrize(
        "setting, map_language, expected",
        [
            (None, None, "ja"),  # saved before the app wrote map_language: unchanged look
            ("auto", None, "ja"),
            (None, "ja", "ja"),
            (None, "en", "en"),
            ("auto", "en-US", "en"),
            (None, "ja-JP", "ja"),
            (None, "fr", "en"),  # no French catalog: English, not Japanese
            ("ja", "en", "ja"),
            ("en", "ja", "en"),
            ("EN", None, "en"),
            ("klingon", "en", "ja"),
        ],
    )
    def test_resolve(self, setting, map_language, expected):
        assert video_text.resolve_language(setting, map_language) == expected

    def test_current_language_reads_the_job_config(self, tmp_path):
        assert video_text.current_language() == "ja"  # no job config loaded
        _config(tmp_path, map_language="en")
        assert video_text.current_language() == "en"

    def test_explicit_choice_beats_map_language(self, tmp_path):
        _config(tmp_path, settings={"video_text_language": "ja"}, map_language="en")
        assert video_text.current_language() == "ja"

    def test_config_without_map_language_stays_japanese(self, tmp_path):
        _config(tmp_path, settings={"fps": 30})
        assert video_text.current_language() == "ja"


class TestStripPrefixes:
    def test_strips_both_languages(self):
        assert video_text.strip_waypoint_prefixes("出発: 和歌山城") == "和歌山城"
        assert video_text.strip_waypoint_prefixes("Departure: Castle") == "Castle"
        assert video_text.strip_waypoint_prefixes("Arrival: Castle") == "Castle"
        assert video_text.strip_waypoint_prefixes("Departure") == ""

    def test_english_word_inside_a_name_survives(self):
        assert video_text.strip_waypoint_prefixes("Arrival Hall") == "Arrival Hall"


class TestHudText:
    def test_japanese_banners_unchanged(self):
        ja = video_text.labels_for("ja")
        assert _hud_text("X", 5, 1, 30, labels=ja)[0] == "まもなく X"
        assert _hud_text("X", 500, 5, 30, labels=ja)[0] == "X へ"
        assert _hud_text("X", 500, 5, 30, mode="ferry", labels=ja)[0] == "X へ 乗船中"

    def test_english_banners(self):
        en = video_text.labels_for("en")
        assert _hud_text("Castle", 5, 1, 30, labels=en)[0] == "Arriving soon: Castle"
        assert _hud_text("Castle", 500, 5, 30, labels=en)[0] == "Heading to Castle"
        assert _hud_text("Port", 500, 5, 30, mode="ferry", labels=en)[0] == "Heading to Port by ferry"

    def test_follows_the_job_config_by_default(self, tmp_path):
        _config(tmp_path, map_language="en")
        assert _hud_text("Castle", 5, 1, 30)[0] == "Arriving soon: Castle"


def _card_engine(tmp_path, language):
    _config(tmp_path, settings={"video_text_language": language})
    return GraphicsEngine()


class TestCards:
    def test_duration_wording(self, tmp_path):
        eng = _card_engine(tmp_path, "en")
        assert eng._format_duration_ja(30) == "30 sec"
        assert eng._format_duration_ja(25 * 60) == "25 min"
        assert eng._format_duration_ja(95 * 60) == "1 h 35 min"
        assert eng._mode_name_ja("ferry") == "Ferry"
        assert eng._mode_duration_label("airplane") == "Flight time"
        ja = _card_engine(tmp_path, "ja")
        assert ja._format_duration_ja(95 * 60) == "1時間35分"
        assert ja._format_duration_ja(30) == "30秒"
        assert ja._mode_name_ja("walking") == "歩く"

    def test_project_override_still_wins(self, tmp_path):
        _config(tmp_path, settings={"video_text_language": "en"})
        eng = GraphicsEngine(summary_card_labels={"total_label": "Sum", "mode_name": {"ferry": "Boat"}})
        assert eng.summary_card_labels["total_label"] == "Sum"
        assert eng.summary_card_labels["mode_name"]["ferry"] == "Boat"
        assert eng.summary_card_labels["mode_name"]["walking"] == "Walk"

    @pytest.mark.parametrize("style", ["glass", "taskbar", "stacked", "columns"])
    def test_english_cards_render_and_differ_from_japanese(self, tmp_path, style):
        kwargs = dict(
            distance_km=12.3, duration_seconds=95 * 60,
            mode_breakdown={"walking": 8.0, "ferry": 4.3}, mode_duration={"walking": 5000.0, "ferry": 700.0},
        )
        frames = {}
        for lang in ("en", "ja"):
            eng = _card_engine(tmp_path, lang)
            eng.summary_card_style = style
            frames[lang] = eng.render_summary_card(**kwargs)
        en = frames["en"]
        assert en.ndim == 3 and en.shape[0] > 40 and en.shape[1] > 100
        assert en.shape != frames["ja"].shape or not np.array_equal(en, frames["ja"])
        # Text that fits leaves the card's outermost columns as background: nothing is clipped at the edge.
        if en.shape[2] == 4:
            assert en[:, -1, 3].max() <= en[:, en.shape[1] // 2, 3].max()


class TestOutro:
    def test_outro_frame_renders_in_english_with_route_info(self, tmp_path):
        _config(tmp_path, settings={"video_text_language": "en"})
        brief = {
            "total_km": 12.3, "total_minutes": 95,
            "legs": [
                {"from": "Start Hall", "to": "A very long destination name that has to be shortened to fit",
                 "km": 8.0, "minutes": 60, "mode": "walking", "pieces": [{"mode": "walking", "km": 8.0, "minutes": 60}]},
                {"from": "A", "to": "Port", "km": 4.3, "minutes": 35, "mode": "ferry",
                 "pieces": [{"mode": "ferry", "km": 4.3, "minutes": 35}]},
            ],
        }
        wps = [{"label": "Start Hall"}, {"label": "Port"}]
        frame = outrocard._build_frame("Trip", wps, brief)
        assert frame.size[0] > 0 and frame.getbbox() is not None
        assert outrocard._outro_subtitle(1) == "1 place visited"
        assert outrocard._outro_subtitle(18) == "18 places visited"

    def test_japanese_subtitle_unchanged(self, tmp_path):
        _config(tmp_path, map_language="ja")
        assert outrocard._outro_subtitle(5) == "訪れた5か所"
