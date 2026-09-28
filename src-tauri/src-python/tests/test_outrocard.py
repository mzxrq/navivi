"""Unit tests for the pure/self-contained helpers in
services/vdoprocessing/outrocard.py (text truncation/centering, thumbnail
cropping, full-frame compositing). ffmpeg-driven generate_outro_clip is
integration-level and out of scope here — exercised via the `outro` CLI
mode instead.
"""

from PIL import Image, ImageDraw

from services.vdoprocessing import outrocard


def _font(size=14):
    return outrocard._load_font(["nonexistent-font-xyz"], size)


class TestLoadFont:
    def test_falls_back_to_default_when_no_candidate_found(self):
        font = outrocard._load_font(["definitely-not-a-real-font.ttf"], 20)
        assert font is not None


class TestTruncateToWidth:
    def test_short_text_unmodified(self):
        img = Image.new("RGB", (200, 50))
        draw = ImageDraw.Draw(img)
        font = _font()
        result = outrocard._truncate_to_width(draw, "short", font, max_width=1000)
        assert result == "short"

    def test_long_text_truncated_with_ellipsis(self):
        img = Image.new("RGB", (200, 50))
        draw = ImageDraw.Draw(img)
        font = _font()
        result = outrocard._truncate_to_width(
            draw, "a very long label that will not fit", font, max_width=30
        )
        assert result.endswith("…")
        assert len(result) < len("a very long label that will not fit")

    def test_extremely_narrow_width_returns_bare_ellipsis(self):
        img = Image.new("RGB", (200, 50))
        draw = ImageDraw.Draw(img)
        font = _font()
        result = outrocard._truncate_to_width(draw, "text", font, max_width=0)
        assert result == "…"


class TestCenterText:
    def test_draws_text_centered_on_x(self):
        img = Image.new("RGB", (200, 50), (0, 0, 0))
        draw = ImageDraw.Draw(img)
        font = _font()
        outrocard._center_text(draw, "hi", font, center_x=100, y=10, fill=(255, 255, 255))
        # Something non-background was drawn somewhere in the image.
        assert img.getextrema() != ((0, 0), (0, 0), (0, 0))


class TestRoundedThumbnail:
    def test_missing_file_returns_none(self, tmp_path):
        result = outrocard._rounded_thumbnail(str(tmp_path / "missing.jpg"), (100, 75))
        assert result is None

    def test_valid_image_is_cropped_and_resized(self, tmp_path):
        src_path = tmp_path / "photo.jpg"
        Image.new("RGB", (400, 100), (200, 100, 50)).save(src_path)
        thumb = outrocard._rounded_thumbnail(str(src_path), (100, 75))
        assert thumb is not None
        assert thumb.size == (100, 75)
        assert thumb.mode == "RGBA"

    def test_alpha_mask_rounds_corners(self, tmp_path):
        src_path = tmp_path / "photo.jpg"
        Image.new("RGB", (100, 100), (255, 0, 0)).save(src_path)
        thumb = outrocard._rounded_thumbnail(str(src_path), (50, 50))
        # Corner pixel should be (mostly) transparent; center should be opaque.
        corner_alpha = thumb.getpixel((0, 0))[3]
        center_alpha = thumb.getpixel((25, 25))[3]
        assert corner_alpha < center_alpha
        assert center_alpha == 255


class TestBuildFrame:
    def test_no_waypoints_still_draws_header(self):
        frame = outrocard._build_frame("My Trip", [])
        assert frame.size == (outrocard._CANVAS_W, outrocard._CANVAS_H)

    def test_frame_includes_thumbnail_grid_for_waypoints_with_images(self, tmp_path):
        img_path = tmp_path / "a.jpg"
        Image.new("RGB", (200, 150), (10, 20, 30)).save(img_path)
        waypoints = [
            {"label": "Osaka", "popup_image": str(img_path)},
            {"label": "Kyoto", "popup_image": str(img_path)},
        ]
        frame = outrocard._build_frame("My Trip", waypoints)
        assert frame.size == (outrocard._CANVAS_W, outrocard._CANVAS_H)
        # Background shouldn't be the only color present once thumbnails paste in.
        colors = frame.getcolors(maxcolors=1_000_000)
        assert colors is not None and len(colors) > 1

    def test_waypoint_with_list_popup_image_uses_first_entry(self, tmp_path):
        img_path = tmp_path / "a.jpg"
        Image.new("RGB", (200, 150), (10, 20, 30)).save(img_path)
        waypoints = [{"label": "Osaka", "popup_image": [str(img_path), "second.jpg"]}]
        # Should not raise even though "second.jpg" doesn't exist.
        frame = outrocard._build_frame("My Trip", waypoints)
        assert frame.size == (outrocard._CANVAS_W, outrocard._CANVAS_H)

    def test_missing_popup_image_file_draws_placeholder_without_raising(self, tmp_path):
        waypoints = [{"label": "Ghost Town", "popup_image": str(tmp_path / "nope.jpg")}]
        frame = outrocard._build_frame("My Trip", waypoints)
        assert frame.size == (outrocard._CANVAS_W, outrocard._CANVAS_H)


SIZE = (outrocard._CANVAS_W, outrocard._CANVAS_H)


class TestBuildScrollPage:
    def _waypoints(self, tmp_path, n):
        img_path = tmp_path / "a.jpg"
        Image.new("RGB", (200, 150), (10, 20, 30)).save(img_path)
        return [{"label": f"Place {i}", "popup_image": str(img_path)} for i in range(n)]

    def _page(self, tmp_path, n, size=SIZE):
        return outrocard._build_scroll_page("My Trip", self._waypoints(tmp_path, n), size)

    def test_ends_with_one_empty_screen_so_cards_scroll_off(self, tmp_path):
        page = self._page(tmp_path, 3)
        assert page.width == SIZE[0]
        bottom = page.crop((0, page.height - SIZE[1], page.width, page.height))
        assert bottom.getcolors() == [(page.width * SIZE[1], outrocard.tuning.OUTRO_BG_COLOR)]

    def test_cards_stay_inside_the_side_padding(self, tmp_path):
        page = self._page(tmp_path, 6)
        pad = outrocard.tuning.OUTRO_SCROLL_SIDE_PADDING
        cards = page.crop((0, outrocard._HEADER_HEIGHT, page.width, page.height))
        for side in (cards.crop((0, 0, pad, cards.height)),
                     cards.crop((page.width - pad, 0, page.width, cards.height))):
            assert side.getcolors() == [(side.width * side.height, outrocard.tuning.OUTRO_BG_COLOR)]

    def test_page_grows_by_one_row_per_three_cards(self, tmp_path):
        six, nine, twelve = (self._page(tmp_path, n) for n in (6, 9, 12))
        assert twelve.height - nine.height == nine.height - six.height > 0

    def test_every_card_is_shown_past_the_grid_cap(self, tmp_path):
        n = outrocard.tuning.OUTRO_MAX_CARDS + 4
        rows = -(-n // outrocard.tuning.OUTRO_SCROLL_COLS)
        assert self._page(tmp_path, n).height >= outrocard._HEADER_HEIGHT + rows * 100

    def test_drawn_at_the_video_size_not_stretched(self, tmp_path):
        small = self._page(tmp_path, 6)
        big = self._page(tmp_path, 6, (1920, 1080))
        assert big.width == 1920
        # Everything scales with the frame: the page keeps its proportions.
        assert abs(big.height / 1080 - small.height / SIZE[1]) < 0.02


class TestScrollOffsets:
    def test_nothing_to_scroll_is_held_still(self):
        offsets = outrocard._scroll_offsets(0, 30)
        assert set(offsets) == {0}
        assert len(offsets) == round(outrocard.tuning.OUTRO_DURATION_SECONDS * 30)

    def test_scrolls_from_top_to_bottom_and_never_backwards(self):
        offsets = outrocard._scroll_offsets(1500, 30)
        assert offsets[0] == 0 and offsets[-1] == 1500
        assert all(b >= a for a, b in zip(offsets, offsets[1:]))

    def test_holds_the_first_screen_and_the_end(self):
        fps = 30
        offsets = outrocard._scroll_offsets(1500, fps)
        start = round(outrocard.tuning.OUTRO_SCROLL_START_HOLD_SECONDS * fps)
        end = round(outrocard.tuning.OUTRO_SCROLL_END_HOLD_SECONDS * fps)
        assert set(offsets[:start]) == {0}
        assert set(offsets[-end:]) == {1500}

    def test_moves_the_same_whole_step_every_frame_while_cruising(self):
        fps = 30
        offsets = outrocard._scroll_offsets(3000, fps, scale=1080 / 704)
        steps = [b - a for a, b in zip(offsets, offsets[1:]) if b != a]
        top = max(steps)
        assert top == round(outrocard.tuning.OUTRO_SCROLL_SPEED_PX * 1080 / 704 / fps)
        # Only the short ease at each end and at most one short
        # leftover step differ from the cruising step.
        assert sum(1 for st in steps if st != top) <= 2 * (top - 1) + 1

    def test_very_long_page_is_capped(self):
        fps = 30
        t = outrocard.tuning
        offsets = outrocard._scroll_offsets(100_000, fps)
        cap = t.OUTRO_SCROLL_MAX_SECONDS + t.OUTRO_SCROLL_START_HOLD_SECONDS + t.OUTRO_SCROLL_END_HOLD_SECONDS
        assert len(offsets) <= round(cap * fps) + 2 * 40
