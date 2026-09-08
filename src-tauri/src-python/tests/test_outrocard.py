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
