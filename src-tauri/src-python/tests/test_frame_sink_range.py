"""Leg clips share the attraction clips' color range, so a stream-copy join does not shift colors."""

import asyncio
import io
import subprocess

from PIL import Image

from services.vdoprocessing.pydeckrecorder.frame_sink import FrameSink


def test_leg_clips_are_limited_range(tmp_path):
    jpeg = io.BytesIO()
    Image.new("RGB", (64, 64), (230, 60, 40)).save(jpeg, "JPEG", quality=95)
    out = tmp_path / "leg.mp4"

    async def run():
        sink = await FrameSink.open(str(out), 24)
        for _ in range(4):
            await sink.write(jpeg.getvalue())
        await sink.finalize()

    asyncio.run(run())
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-show_entries", "stream=pix_fmt,color_range",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True, check=True).stdout.strip()
    assert probe == "yuv420p,tv"
