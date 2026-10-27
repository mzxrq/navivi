"""English overview text: whole-word card lines, letters the font lacks, translated titles; Japanese unchanged."""

from PIL import Image, ImageDraw

from services.mapfetcher.graphicengine.base import _GraphicsEngineBase
from services.mapfetcher.graphicengine.glyphs import drawable
from services.mapfetcher.graphicengine.popup_box import _PopupBoxMixin
from services.localization.overview_script import course_taglines


class _Box(_PopupBoxMixin, _GraphicsEngineBase):
    def __init__(self):
        self.theme, self._font_cache = "light", {}


def _fit(text, width=170):
    box = _Box()
    font = box._card_font(box.FONT_CANDIDATES_REGULAR, 22)
    return box._fit_label_caption(ImageDraw.Draw(Image.new("RGBA", (1, 1))), text, font, box.FONT_CANDIDATES_REGULAR, width)[0]


def test_english_card_lines_break_between_words():
    assert _fit("Katsuragi Mikumari Shrine") in (["Katsuragi", "Mikumari Shrine"], ["Katsuragi Mikumari", "Shrine"])


def test_japanese_card_lines_split_as_before():
    lines = _fit("葛城一言主神社と九品寺の石仏群", 120)
    assert len(lines) == 2 and "".join(lines) == "葛城一言主神社と九品寺の石仏群"


def test_missing_letters_fall_back_and_japanese_is_untouched():
    assert drawable("Sixth Jizō stone statues") == "Sixth Jizo stone statues"
    assert drawable("Shōfuku-ji “Kuhon-ji”") == "Shofuku-ji “Kuhon-ji”"
    assert drawable("友ヶ島・加太をめぐる道") == "友ヶ島・加太をめぐる道"


def _brief():
    leg = {"from": "S", "to": "B", "from_at": [34.0, 135.0], "to_at": [34.1, 135.1], "mode": "walking"}
    return {"start": "S", "legs": [leg]}


def test_course_titles_follow_the_video_language():
    ja = {"video_title": "葛城修験", "map_language": "ja", "settings": {"video_text_language": "ja"}}
    assert course_taglines(ja, {**_brief(), "start": "寺田橋", "legs": [{**_brief()["legs"][0], "to": "吉祥草寺"}]})[:3] == [
        "葛城修験", "寺田橋から、吉祥草寺へ", "寺田橋から歩いてめぐる道"]
    en = {"video_title": "Katsuragi Shugen", "project_name": "16_folder", "map_language": "en",
          "settings": {"video_text_language": "en"}}
    assert course_taglines(en, _brief())[:3] == ["Katsuragi Shugen", "From S to B", "A walk from S"]
    assert "16_folder" not in course_taglines({**en, "video_title": ""}, _brief())
