"""Where a walking leg's frames go: an ffmpeg process fed JPEG screenshots, which a stop-by's photo pause can
cut into a further "_cont{n}" file mid-leg (the page keeps running, only the sink changes)."""

import asyncio
import os
from pathlib import Path

from services import tuning

from .common import logger


class FrameSink:
    """`proc_ref` is the current clip ({"proc", "temp_path", "real_path"}), `produced_paths` every clip so far,
    `frame_state` the frames written ({"count", "last", "cuts", "clip_start"}): the opening's length (see
    start_cue_seconds) is measured from it, not predicted."""

    def __init__(self, output_path: str, fps: int):
        from services.vdoprocessing.vdoeditor import FFmpegEngine

        self.output_path = output_path
        self.fps = fps
        self.editor = FFmpegEngine()
        self.proc_ref: dict = {}
        self.produced_paths = [output_path]
        self.frame_state = {"count": 0, "last": None, "cuts": 0, "clip_start": 0}

    @classmethod
    async def open(cls, output_path: str, fps: int) -> "FrameSink":
        sink = cls(output_path, fps)
        proc, temp = await sink._spawn_ffmpeg(output_path)
        sink.proc_ref.update(proc=proc, temp_path=temp, real_path=output_path)
        return sink

    async def _spawn_ffmpeg(self, out_path: str):
        # Encodes into a private temp file in out_path's own directory
        # (same convention as VideoExporter, which the overview/waypoints
        # renderers already use), not out_path itself -- see
        # `finalize`, the only place that ever touches out_path, so
        # a render killed mid-stream leaves only that throwaway temp file
        # behind instead of a half-written/corrupted final video.
        from services.vdoprocessing.vdoexporter import VideoExporter

        temp_path = VideoExporter._make_temp_path(out_path)
        ffmpeg_cmd = [
            self.editor.resolve_binary(), "-y", *tuning.ffmpeg_log_args(),
            "-f", "image2pipe", "-vcodec", "mjpeg", "-framerate", str(self.fps), "-i", "-",
            "-c:v", "libx264", *tuning.ffmpeg_thread_args(),
            "-r", str(self.fps), "-pix_fmt", "yuv420p", temp_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *ffmpeg_cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL
        )
        return proc, temp_path

    async def write(self, png_bytes: bytes) -> None:
        self.proc_ref["proc"].stdin.write(png_bytes)
        await self.proc_ref["proc"].stdin.drain()
        self.frame_state["count"] += 1
        self.frame_state["last"] = png_bytes

    async def finalize(self) -> None:
        """Closes the CURRENT clip's ffmpeg process and, only once it's
        confirmed a clean exit, atomically renames its temp file onto its
        real target path -- the one moment that real path is ever touched.
        A crash/nonzero exit instead deletes the temp file and leaves
        whatever was already at the real path (if anything) untouched."""
        from services.vdoprocessing.vdoexporter import _replace_with_retry

        proc_ref = self.proc_ref
        proc_ref["proc"].stdin.close()
        await proc_ref["proc"].wait()
        if proc_ref["proc"].returncode == 0:
            _replace_with_retry(proc_ref["temp_path"], proc_ref["real_path"])
        else:
            logger.error(
                f"[ERROR] FFmpeg exited {proc_ref['proc'].returncode} while "
                f"producing '{proc_ref['real_path']}' -- leaving it untouched."
            )
            Path(proc_ref["temp_path"]).unlink(missing_ok=True)

    async def cut(self) -> None:
        """Finalizes the current file and opens a fresh one for `write` -- see
        `_play_stopby_photo_pause`, the only caller. The continuation keeps
        this leg's "02_waypoint_{N:02d}_" prefix with a "_cont{n}" suffix, so
        timeline_step.py's filename parse still resolves it to this leg."""
        await self.finalize()
        stem, ext = os.path.splitext(self.output_path)
        new_path = f"{stem}_cont{len(self.produced_paths) + 1}{ext}"
        new_proc, new_temp = await self._spawn_ffmpeg(new_path)
        self.proc_ref.update(proc=new_proc, temp_path=new_temp, real_path=new_path)
        self.produced_paths.append(new_path)
        self.frame_state["cuts"] += 1
        self.frame_state["clip_start"] = self.frame_state["count"]
