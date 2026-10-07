"""The caption look extras (shadow, shadow colour, letter spacing, text opacity) really reach the exported video.

Each test burns a short caption onto a black frame through the real ffmpeg/libass, grabs a frame and measures it, once per
render path: the editor export (.ass), the pipeline's .srt burn (force_style) and a text-track item (override tags)."""

import subprocess

import pytest

from services.vdoprocessing.vdoexporter import VideoExporter, caption_subtitle_style, write_caption_ass

np = pytest.importorskip("numpy")
Image = pytest.importorskip("PIL.Image")

FFMPEG = VideoExporter.resolve_ffmpeg()
pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg not available")

SIZE = (960, 540)
BASE = {"font_family": "Arial", "font_size": 90, "color": "#ffffff", "outline_width": 0, "background": False, "position": "middle", "bold": True}


def _ffmpeg(*args):
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *args], check=True)


@pytest.fixture(scope="module")
def black(tmp_path_factory):
    path = tmp_path_factory.mktemp("black") / "black.mp4"
    _ffmpeg("-f", "lavfi", "-i", f"color=c=black:s={SIZE[0]}x{SIZE[1]}:r=10:d=2", "-pix_fmt", "yuv420p", str(path))
    return path


def _frame(tmp_path, black, name, how, look):
    """The frame (H x W x 3) of a black 2 s clip with 'HIHI' burned in `how` with `look` on top of BASE."""
    out = tmp_path / f"{name}_out.mp4"
    style = {**BASE, **look}
    if how == "srt":
        srt = tmp_path / f"{name}.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:02,000\nHIHI\n", encoding="utf-8")
        VideoExporter.burn_subtitles(str(black), str(srt), str(out), caption_subtitle_style(style, check_font=False))
    else:
        ass = tmp_path / f"{name}.ass"
        if how == "ass":
            write_caption_ass([{"start": 0, "end": 2, "text": "HIHI"}], style, SIZE, ass, check_font=False)
        else:
            item = {"start": 0, "end": 2, "animation": "none", "title": {"text": "HIHI", "style": style, "animation": "none"}}
            write_caption_ass([], None, SIZE, ass, check_font=False, texts=[item])
        VideoExporter.burn_subtitles(str(black), str(ass), str(out))
    png = tmp_path / f"{name}.png"
    _ffmpeg("-ss", "1", "-i", str(out), "-frames:v", "1", str(png))
    return np.asarray(Image.open(png).convert("RGB")).astype(int)


def _bright_width(frame):
    cols = np.where(frame.max(axis=2).max(axis=0) > 128)[0]
    return int(cols.max() - cols.min()) if cols.size else 0


def _red_pixels(frame):
    r, g, b = frame[..., 0], frame[..., 1], frame[..., 2]
    return int(((r > 100) & (g < 60) & (b < 60)).sum())


PATHS = ["ass", "srt", "text"]


@pytest.mark.parametrize("how", PATHS)
def test_shadow_and_its_colour_are_drawn(tmp_path, black, how):
    off = _frame(tmp_path, black, "off", how, {"shadow": 0, "shadow_color": "#ff0000"})
    on = _frame(tmp_path, black, "on", how, {"shadow": 12, "shadow_color": "#ff0000"})
    assert _red_pixels(off) == 0
    assert _red_pixels(on) > 200


@pytest.mark.parametrize("how", PATHS)
def test_letter_spacing_widens_the_line(tmp_path, black, how):
    tight = _bright_width(_frame(tmp_path, black, "tight", how, {"shadow": 0, "letter_spacing": 0}))
    wide = _bright_width(_frame(tmp_path, black, "wide", how, {"shadow": 0, "letter_spacing": 20}))
    assert tight > 40
    assert wide >= tight + 25  # 3 gaps of 20 px at 1080p, halved on this 540-line frame


@pytest.mark.parametrize("how", PATHS)
def test_text_opacity_dims_the_fill(tmp_path, black, how):
    full = _frame(tmp_path, black, "full", how, {"shadow": 0, "opacity": 1})
    half = _frame(tmp_path, black, "half", how, {"shadow": 0, "opacity": 0.4})
    assert full.max() > 240
    assert 60 < half.max() < 160
