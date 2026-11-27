"""A full-range clip (a still photo clip, an old leg) is converted before the stream-copy join."""

import subprocess

import numpy as np
from PIL import Image

from services.vdoprocessing.vdoexporter import VideoExporter

COLOR = (230, 60, 40)


def _still(tmp_path, name, picture):
    Image.new("RGB", (64, 64), COLOR).save(tmp_path / picture)
    out = tmp_path / name
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(tmp_path / picture), "-t", "1",
                    "-vf", "format=yuv420p", "-r", "24", "-c:v", "libx264", str(out)], check=True)
    return out


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=pix_fmt,color_range", "-of", "default=nk=1:nw=1", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return out.split()


def test_a_full_range_clip_is_converted_and_keeps_its_color(tmp_path):
    clip = _still(tmp_path, "still.mp4", "photo.jpg")
    assert _probe(clip) == ["yuvj420p", "pc"]  # what a still clip from a JPEG comes out as
    segment = VideoExporter._mux_track_for_concat("ffmpeg", clip, None, tmp_path, 0)
    assert _probe(segment) == ["yuv420p", "tv"]
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(segment), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    assert np.abs(np.frombuffer(raw, np.uint8)[:3].astype(int) - COLOR).max() <= 4


def test_a_limited_range_clip_is_not_converted(tmp_path):
    clip = _still(tmp_path, "limited.mp4", "photo.png")
    assert VideoExporter._segment_video_filters(0, clip, None, None, 0.0, 0.0, None, 0.0) == []
