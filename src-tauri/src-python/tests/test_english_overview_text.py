"""English overview text: whole-word card lines, letters the font lacks, translated titles; Japanese unchanged."""

from PIL import Image, ImageDraw

from services.mapfetcher.graphicengine.base import _GraphicsEngineBase
from services.mapfetcher.graphicengine.glyphs import drawable
from services.mapfetcher.graphicengine.popup_box import _PopupBoxMixin


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
