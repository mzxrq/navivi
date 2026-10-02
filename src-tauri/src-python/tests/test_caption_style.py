"""Burned-in captions: a narrow translucent box built from the project's subtitle settings, used by both burn paths."""

from pathlib import Path

import pytest

from services import tuning
from services.localization.subtitle import caption_style
from services.vdoprocessing import vdoexporter
from services.vdoprocessing.vdoexporter import VideoExporter
from services.vdoprocessing.videopipeline.subtitle_step import _burn_checkpoint_key


def _fields(style):
    return dict(pair.split("=", 1) for pair in style.to_force_style().split(","))


def test_defaults_are_a_narrow_translucent_box_at_the_bottom_centre():
    f = _fields(caption_style({}))
    assert f["BorderStyle"] == "3" and f["Shadow"] == "0" and f["Alignment"] == "2"
    assert f["FontSize"] == str(tuning.CAPTION_DEFAULT_SIZE) and f["FontName"] == "Yu Gothic UI"
    assert f["PrimaryColour"] == "&H00FFFFFF"
    assert f["OutlineColour"] == tuning.CAPTION_BOX_COLOR  # libass paints the box with the outline colour
    assert f["MarginV"] == str(tuning.CAPTION_MARGIN_V)


def test_side_margins_leave_the_box_the_configured_share_of_the_width():
    f = _fields(caption_style(None))
    left, right = int(f["MarginL"]), int(f["MarginR"])
    assert left == right
    assert (tuning.CAPTION_PLAY_RES_X - left - right) / tuning.CAPTION_PLAY_RES_X == pytest.approx(tuning.CAPTION_MAX_WIDTH, abs=0.01)


def test_project_settings_override_the_look():
    f = _fields(
        caption_style(
            {
                "subtitle_font": "Meiryo",
                "subtitle_font_size": "20",
                "subtitle_color": "&H0000FFFF",
                "subtitle_outline_color": "&H00000000",
                "subtitle_bold": True,
            }
        )
    )
    assert (f["FontName"], f["FontSize"], f["PrimaryColour"], f["OutlineColour"], f["Bold"]) == ("Meiryo", "20", "&H0000FFFF", "&H00000000", "-1")


@pytest.mark.parametrize("empty", [None, "", 0])
def test_empty_settings_fall_back_to_the_defaults(empty):
    f = _fields(caption_style({"subtitle_font": empty, "subtitle_font_size": empty, "subtitle_color": empty, "subtitle_outline_color": empty}))
    assert f["FontName"] == "Yu Gothic UI" and f["FontSize"] == str(tuning.CAPTION_DEFAULT_SIZE)
    assert f["PrimaryColour"] == "&H00FFFFFF" and f["OutlineColour"] == tuning.CAPTION_BOX_COLOR


@pytest.fixture
def ffmpeg_calls(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).write_bytes(b"x")
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(vdoexporter.subprocess, "run", fake_run)
    monkeypatch.setattr(VideoExporter, "resolve_ffmpeg", staticmethod(lambda: "ffmpeg"))
    (tmp_path / "in.mp4").write_bytes(b"v")
    (tmp_path / "in.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n", encoding="utf-8")
    return calls


def _filter(cmd):
    return cmd[cmd.index("-vf") + 1]


def test_burn_without_a_style_keeps_ffmpegs_default_look(tmp_path, ffmpeg_calls):
    VideoExporter.burn_subtitles(str(tmp_path / "in.mp4"), str(tmp_path / "in.srt"), str(tmp_path / "out.mp4"))
    assert "force_style" not in _filter(ffmpeg_calls[0])


def test_burn_with_a_style_passes_it_to_libass(tmp_path, ffmpeg_calls):
    style = caption_style({"subtitle_font_size": 22})
    VideoExporter.burn_subtitles(str(tmp_path / "in.mp4"), str(tmp_path / "in.srt"), str(tmp_path / "out.mp4"), style=style)
    flt = _filter(ffmpeg_calls[0])
    assert f"force_style='{style.to_force_style()}'" in flt and "FontSize=22" in flt and "BorderStyle=3" in flt


def test_timeline_export_burns_with_the_style_written_into_timeline_json(tmp_path, ffmpeg_calls):
    out = tmp_path / "joined.mp4"
    out.write_bytes(b"v")
    data = {
        "subtitles": [{"start": 0, "end": 1, "text": "hi"}],
        "burn_subtitles": True,
        "subtitle_style": {"subtitle_font_size": 24, "subtitle_color": "&H0000FFFF"},
    }
    VideoExporter._finish_timeline_output("ffmpeg", data, str(out), tmp_path)
    flt = _filter(ffmpeg_calls[0])
    assert "FontSize=24" in flt and "PrimaryColour=&H0000FFFF" in flt


def test_timeline_export_without_a_style_block_uses_the_default_caption_look(tmp_path, ffmpeg_calls):
    out = tmp_path / "joined.mp4"
    out.write_bytes(b"v")
    VideoExporter._finish_timeline_output("ffmpeg", {"subtitles": [{"start": 0, "end": 1, "text": "hi"}], "burn_subtitles": True}, str(out), tmp_path)
    assert f"FontSize={tuning.CAPTION_DEFAULT_SIZE}" in _filter(ffmpeg_calls[0])


def test_changing_the_style_makes_an_already_burned_clip_stale(tmp_path):
    video, srt = tmp_path / "clip.mp4", tmp_path / "clip.srt"
    video.write_bytes(b"v")
    srt.write_text("cues", encoding="utf-8")
    base = _burn_checkpoint_key(str(video), str(srt), caption_style({}))
    assert base == _burn_checkpoint_key(str(video), str(srt), caption_style({}))
    assert base != _burn_checkpoint_key(str(video), str(srt), caption_style({"subtitle_color": "&H0000FFFF"}))
    assert base != _burn_checkpoint_key(str(video), str(srt), None)
