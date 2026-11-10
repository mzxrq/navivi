import subprocess

import numpy as np
import pytest

from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing.vdoexporter import VideoExporter

FFMPEG = FFmpegManager.resolve_ffmpeg_bin()


def _clip(path, seconds, freq, volume):
    subprocess.run([
        FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=gray:s=160x90:r=30:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}", "-af", f"volume={volume}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ], check=True)


def test_the_next_clips_voice_starts_at_full_volume_under_the_dissolve(tmp_path):
    first, second = tmp_path / "a.mp4", tmp_path / "b.mp4"
    _clip(first, 2.0, 440, 0.0)  # a leg whose voice has ended
    _clip(second, 2.0, 880, 0.5)  # the attraction clip's voice
    out = VideoExporter._crossfade_pair(FFMPEG, first, second, 0.8, tmp_path, 0)
    if out is None:
        pytest.skip("ffmpeg could not build the dissolve here")
    raw = subprocess.run([FFMPEG, "-loglevel", "error", "-i", str(out), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32)
    rms = lambda s, e: float(np.sqrt((a[int(s * 8000):int(e * 8000)] ** 2).mean()))  # noqa: E731
    full = rms(2.6, 3.4)
    assert rms(2.05, 2.25) > 0.8 * full  # the first moment of the second clip is already loud: no fade-in
