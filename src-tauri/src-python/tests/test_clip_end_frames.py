"""The attraction clip's end frames, which the legs on either side show as their own pictures."""

import os
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

from services.vdoprocessing.video_frames import clip_end_frames


def _clip(path: Path, source: str = "testsrc2") -> str:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"{source}=size=160x90:rate=24",
                    "-frames:v", "36", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)
    return str(path)


def _frame(clip: str, n: int, out: Path) -> np.ndarray:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", clip, "-vf", f"select=eq(n\\,{n})",
                    "-frames:v", "1", str(out)], check=True)
    return np.asarray(Image.open(out).convert("RGB"))


def test_returns_the_first_and_last_frames(tmp_path):
    clip = _clip(tmp_path / "04_attraction_01_石標.mp4")
    first, last = clip_end_frames(clip, str(tmp_path / "frames"))
    assert Path(first).name.startswith("04_attraction_01_石標_first_")
    assert Path(last).name.startswith("04_attraction_01_石標_last_")
    assert np.array_equal(np.asarray(Image.open(first).convert("RGB")), _frame(clip, 0, tmp_path / "a.png"))
    assert np.array_equal(np.asarray(Image.open(last).convert("RGB")), _frame(clip, 35, tmp_path / "b.png"))
    assert sorted(p.name for p in (tmp_path / "frames").iterdir()) == sorted([Path(first).name, Path(last).name])


def test_names_follow_the_picture(tmp_path):
    clip = _clip(tmp_path / "c.mp4")
    before = clip_end_frames(clip, str(tmp_path / "frames"))
    assert clip_end_frames(clip, str(tmp_path / "frames")) == before
    _clip(tmp_path / "c.mp4", "smptebars")  # the clip is remade
    assert clip_end_frames(clip, str(tmp_path / "frames")) != before


def test_an_unchanged_picture_keeps_its_file_time(tmp_path):
    clip = _clip(tmp_path / "c.mp4")
    frames = clip_end_frames(clip, str(tmp_path / "frames"))
    for frame in frames:
        os.utime(frame, (1_000_000, 1_000_000))
    clip_end_frames(clip, str(tmp_path / "frames"))
    # The legs hash each photo's mtime: a rewrite re-rendered every one of them on every run.
    assert [os.stat(f).st_mtime for f in frames] == [1_000_000, 1_000_000]


def test_a_broken_clip_gives_nothing(tmp_path):
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"")
    assert clip_end_frames(str(broken), str(tmp_path / "frames")) is None
    assert clip_end_frames(str(tmp_path / "gone.mp4"), str(tmp_path / "frames")) is None
    assert list((tmp_path / "frames").iterdir()) == []
