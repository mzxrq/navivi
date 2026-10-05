"""
services/video_exporter.py
---------------------------------------------------------------------------
Handles writing frames to video files using FFmpeg or OpenCV fallback.

[REFACTOR NOTE]
Two silent-failure bugs fixed in this pass:

  1. `release()` previously called `self.proc.wait()` and returned
     `output_path` unconditionally — NEVER checking `returncode`. If
     ffmpeg died (bad codec params, disk full, malformed frame stream),
     the caller received a "successful" path pointing at a missing or
     truncated file. The failure would then only surface several stages
     later (e.g. during `concat_from_timeline`'s pre-flight existence
     check, or worse, a downstream ffmpeg concat silently producing a
     corrupt final video) with no link back to the real root cause.

  2. Both stdout AND stderr were piped to `DEVNULL`, so even if we HAD
     checked the exit code, there was no diagnostic text to report.

Fix: stderr is now captured via `subprocess.PIPE` and drained with
`Popen.communicate()` rather than a bare `.wait()`. This matters: per the
Python docs, calling `.wait()` while a child process has a PIPE'd stream
you haven't read risks a classic pipe-full deadlock (child blocks writing
to stderr once the OS pipe buffer is full; you're blocked in `.wait()`
waiting for it to exit; neither side ever proceeds). `communicate()`
reads and waits atomically, so this can't happen. Non-zero exit codes now
raise immediately with the stderr tail attached.
---------------------------------------------------------------------------
"""

from dataclasses import replace
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple
import uuid

import cv2
import numpy as np

from services import runtime_paths, tuning
from services.localization.subtitle import SubtitleStyle
from services.localization.text_style import TextStyle, wrap_text
from services.logger.logger import setup_logger

# The editor preview's caption: white text on a 60% black box, low in the frame.
# settings.caption_style overrides it per project.
DEFAULT_CAPTION_STYLE = TextStyle(
    font_family="Meiryo",
    font_size=71,
    bold=False,
    shadow=0.0,
    outline_width=9.375,
    background=True,
    background_opacity=0.6,
    margin_v=75,
)
EDITOR_SUBTITLE_STYLE = DEFAULT_CAPTION_STYLE.to_subtitle_style()


def caption_subtitle_style(raw: Optional[dict], check_font: bool = True) -> SubtitleStyle:
    style = DEFAULT_CAPTION_STYLE.merged(raw)
    if check_font:
        style = style.with_installed_font(DEFAULT_CAPTION_STYLE.font_family)
    return style.to_subtitle_style()


def subtitle_band_px(frame_h: int, style: SubtitleStyle = EDITOR_SUBTITLE_STYLE, lines: int = 2) -> int:
    """Height (px) of the bottom band a burned caption of `lines` lines can cover
    (0 when captions sit at the middle or top). libass scales SRT style values
    from its default PlayResY of 288."""
    if style.alignment not in (1, 2, 3):
        return 0
    units = style.margin_v + lines * style.font_size * 1.25 + 2 * style.outline
    return int(round(units * frame_h / 288))


def _subtitle_display_text(text: str, max_chars_per_line: int = 0) -> str:
    """Wraps to max_chars_per_line, then drops each line's closing 。/、: the mark sits
    left in its full-width cell, leaving the caption box wider on the right. Same
    rule as subtitleDisplayText in Preview.tsx."""
    text = wrap_text("\n".join(l.strip() for l in text.strip().splitlines()), max_chars_per_line)
    lines = [line.strip().rstrip("。、").rstrip() or line.strip() for line in text.splitlines()]
    return "\n".join(lines)


def _ass_timestamp(seconds: float) -> str:
    cs = max(0, int(round(seconds * 100)))
    h, cs = divmod(cs, 360_000)
    m, cs = divmod(cs, 6_000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    # Braces open override tags and backslashes start escapes; show them as full-width look-alikes.
    return text.replace("\\", "＼").replace("{", "｛").replace("}", "｝").replace("\n", "\\N")


def write_caption_ass(
    cues: list, shared_style: Optional[dict], frame_size: Optional[Tuple[int, int]], path: Path,
    check_font: bool = True,
    texts: Optional[list] = None,
) -> Path:
    """Burned captions as .ass: every cue gets the shared style (settings.caption_style)
    with its own `style` overrides on top, so lines can differ in font, colour and place.
    `texts` are text-track items (an animated title + subtitle, centred), drawn on top."""
    from services.vdoprocessing.introclip import (
        DEFAULT_SUBTITLE_STYLE,
        DEFAULT_TITLE_STYLE,
        TEXT_DEFAULT_MARGIN_PX,
        text_block_center_y,
        title_events,
    )

    shared = DEFAULT_CAPTION_STYLE.merged(shared_style)
    w, h = frame_size or (1920, 1080)
    play_w = round(1080 * w / h)
    fonts: dict = {}

    def installed(style: TextStyle, fallback: str) -> TextStyle:
        if not check_font:
            return style
        if style.font_family not in fonts:
            fonts[style.font_family] = style.with_installed_font(fallback).font_family
        return replace(style, font_family=fonts[style.font_family])

    styles: dict = {}
    events = []
    for cue in sorted(cues, key=lambda c: float(c["start"])):
        style = installed(shared.merged(cue.get("style")), DEFAULT_CAPTION_STYLE.font_family)
        name = styles.setdefault(style, f"S{len(styles)}")
        text = _ass_text(_subtitle_display_text(str(cue["text"]), style.max_chars_per_line))
        events.append(
            f"Dialogue: 0,{_ass_timestamp(float(cue['start']))},{_ass_timestamp(float(cue['end']))},"
            f"{name},,0,0,0,,{text}"
        )
    for item in sorted(texts or [], key=lambda x: float(x["start"])):
        title, subtitle = item.get("title") or {}, item.get("subtitle") or {}
        title_text, sub_text = str(title.get("text") or ""), str(subtitle.get("text") or "")
        title_style = installed(DEFAULT_TITLE_STYLE.merged(title.get("style")), DEFAULT_TITLE_STYLE.font_family)
        sub_style = installed(DEFAULT_SUBTITLE_STYLE.merged(subtitle.get("style")), DEFAULT_SUBTITLE_STYLE.font_family)
        def px(key: str) -> float:
            v = item.get(key)
            return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else TEXT_DEFAULT_MARGIN_PX

        cy = text_block_center_y(
            str(item.get("position") or "middle"), px("margin_v"),
            title_style.font_size, sub_style.font_size, bool(title_text.strip()), bool(sub_text.strip()),
        )
        align = item.get("align") if item.get("align") in ("left", "right") else "center"
        cx = {"left": px("margin_h"), "right": play_w - px("margin_h")}.get(align, play_w / 2)
        for a, b, text in title_events(
            title_text, sub_text, float(item["start"]), float(item["end"]),
            title_style, sub_style, int(round(cx)), cy, align=align,
            animation=item.get("animation"),
            title_motion={"animation": title.get("animation"), "delay": title.get("delay")},
            subtitle_motion={"animation": subtitle.get("animation"), "delay": subtitle.get("delay")},
        ):
            # Layer 1: above captions. Every look is in the event's own tags.
            events.append(f"Dialogue: 1,{_ass_timestamp(a)},{_ass_timestamp(b)},Text,,0,0,0,,{text}")
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 0\nScaledBorderAndShadow: yes\n"
        # 1080 lines tall, as wide as the frame's aspect, so style px read as 1080p px.
        f"PlayResX: {play_w}\nPlayResY: 1080\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        + "".join(s.to_ass_style_line(n) + "\n" for s, n in styles.items())
        + "Style: Text,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n"
        + "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        + "".join(e + "\n" for e in events),
        encoding="utf-8",
    )
    return path


def _run_with_progress(
    cmd: List[str], input_path: str, on_progress: Callable[[float], None]
) -> subprocess.CompletedProcess:
    """Runs an ffmpeg command, calling on_progress(0..1) from ffmpeg's -progress output."""
    from services.tts.ttsengine import FFmpegManager

    try:
        total = FFmpegManager.get_media_duration(input_path)
    except (RuntimeError, OSError):
        total = 0.0
    # -progress goes before the output path; stderr goes to a file so an unread pipe can't stall ffmpeg.
    cmd = [c for c in cmd[:-1] if c != "-stats"] + ["-progress", "pipe:1", "-nostats", cmd[-1]]
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as err:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, encoding="utf-8", errors="replace")
        for line in proc.stdout:
            key, _, value = line.strip().partition("=")
            if key == "out_time_us" and total > 0 and value.isdigit():
                on_progress(min(1.0, int(value) / 1e6 / total))
        proc.wait()
        err.seek(0)
        return subprocess.CompletedProcess(cmd, proc.returncode, "", err.read())

# [NOTE] [Editor] This module previously had no logger at all — every ffmpeg
# failure was either swallowed (DEVNULL) or surfaced as a bare exception
# with no context. Matches the `setup_logger` convention used everywhere
# else in this codebase.
logger = setup_logger("VideoExporter")

# Cap on how much stderr tail we keep in memory/log per failure. Ffmpeg
# verbose logs can run to megabytes; we only need the last chunk (where
# the fatal error line lives) for diagnostics, not the entire stream.
_STDERR_TAIL_BYTES = 4000

# Retry budget for the final os.replace() onto output_path — on Windows a
# just-finished output file can be transiently held open by something with
# no real stake in it (Explorer's thumbnail/preview handle, an antivirus
# scan, a media player the user has the previous render open in) for a
# few hundred ms right as this process tries to replace it, which raises
# PermissionError (WinError 5) even though nothing is actually wrong with
# the render itself. A short retry-with-backoff clears the transient case
# instead of failing the whole render over someone else's file handle.
_REPLACE_RETRY_ATTEMPTS = 5
_REPLACE_RETRY_DELAY_SECONDS = 0.5


def sweep_stale_temp_files(directory, recursive: bool = False, min_age_seconds: float = 600) -> int:
    """Deletes ".<name>.<uuid>.tmp.<ext>" files left by killed renders. Files
    touched within `min_age_seconds` are kept, since a live render may own them."""
    d = Path(directory)
    if not d.is_dir():
        return 0
    cutoff = time.time() - min_age_seconds
    removed = 0
    for p in (d.rglob(".*.tmp.*") if recursive else d.glob(".*.tmp.*")):
        try:
            if p.is_file() and p.stat().st_mtime < cutoff:
                p.unlink()
                removed += 1
        except OSError:
            pass
    if removed:
        logger.info("Removed %d leftover temp file(s) from %s", removed, d)
    return removed


def _replace_with_retry(src: str, dst: str) -> None:
    for attempt in range(_REPLACE_RETRY_ATTEMPTS):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRY_ATTEMPTS - 1:
                raise
            logger.warning(
                "Replacing '%s' was denied (attempt %d/%d) — likely still "
                "open in another program (a preview/player/antivirus scan). "
                "Retrying shortly.",
                dst, attempt + 1, _REPLACE_RETRY_ATTEMPTS,
            )
            time.sleep(_REPLACE_RETRY_DELAY_SECONDS)


# Every concat segment is written with this MP4 video time base, so the final
# stream-copy join never mixes time bases (see concat_from_timeline).
_TIMESCALE = 15360


class VideoExporter:
    def __init__(self, output_path: str, width: int, height: int, fps: int):
        self.width = width
        self.height = height
        self.fps = fps
        self.output_path = output_path
        # Every frame is written to a private temp file in the SAME
        # directory as output_path (same filesystem — required for the
        # os.replace() in release() to be an atomic rename rather than a
        # copy) instead of straight to output_path itself. output_path
        # is only ever touched once, at the very end of a SUCCESSFUL
        # release() — so a render that's killed mid-stream (e.g. the
        # app's cancel button, which SIGKILLs this whole process) leaves
        # only this throwaway temp file corrupted; whatever valid video
        # already existed at output_path before this render started is
        # never overwritten.
        self._temp_path = self._make_temp_path(output_path)
        self.proc = self._open_ffmpeg_writer(self._temp_path)
        self._fallback_path = None
        self._fallback_writer = None
        # Frames written so far: where in the clip (frames / fps seconds) the
        # next one lands, for timing that has to meet the narration.
        self.frames_written = 0

        if self.proc is None:
            self._fallback_path = tempfile.mktemp(suffix=".avi")
            self._fallback_writer = cv2.VideoWriter(
                self._fallback_path,
                cv2.VideoWriter.fourcc(*"XVID"),
                self.fps,
                (self.width, self.height),
            )
            if not self._fallback_writer.isOpened():
                raise RuntimeError(
                    "Neither ffmpeg nor OpenCV VideoWriter is available."
                )

    @staticmethod
    def _make_temp_path(output_path: str) -> str:
        """A private, collision-safe path in output_path's OWN directory
        (not the OS temp dir — os.replace() in release() needs same-
        filesystem to be atomic) to write into instead of output_path
        directly. Leading "." hides it from a casual directory listing;
        the uuid suffix means two concurrent renders into the same
        directory (or a leftover temp file from a killed previous run)
        can never collide on the same path."""
        out_path = Path(output_path)
        sweep_stale_temp_files(out_path.parent)
        return str(
            out_path.with_name(f".{out_path.stem}.{uuid.uuid4().hex[:8]}.tmp{out_path.suffix}")
        )

    @staticmethod
    def resolve_ffmpeg() -> Optional[str]:
        return runtime_paths.ffmpeg_exe()

    def _open_ffmpeg_writer(self, output_path: str) -> Optional[subprocess.Popen]:
        ffmpeg_cmd = self.resolve_ffmpeg()
        if ffmpeg_cmd is None:
            return None

        cmd = [
            ffmpeg_cmd,
            "-y", *tuning.ffmpeg_pipe_log_args(),
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self.width}x{self.height}",
            "-r",
            str(self.fps),
            "-i",
            "-",
            "-an",
            "-vcodec",
            "libx264",
            *tuning.ffmpeg_thread_args(),
            "-crf",
            "18",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            output_path,
        ]
        # [FIXME] [Editor] stderr must stay PIPE'd and only ever be drained via
        # communicate() — a bare .wait() here deadlocks once ffmpeg fills the pipe buffer.
        return subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            # [NOTE] [Editor] was DEVNULL — now captured so failures are
            # diagnosable. Drained exclusively via communicate() (never
            # a bare .wait()) to avoid the pipe-full deadlock described
            # in the module docstring.
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def write(self, frame: np.ndarray) -> None:
        self.frames_written += 1
        if self.proc is not None and self.proc.stdin:
            try:
                self.proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError) as exc:
                # [NOTE] [Editor] ffmpeg died mid-stream. Previously this exception
                # would propagate bare (or, in FrameSink's variant, get
                # silently swallowed) with zero indication of *why* the
                # encoder process exited. `communicate()` here safely
                # drains any buffered stderr and reaps the process so we
                # can attach the real ffmpeg error message instead of
                # letting every subsequent frame re-raise the same
                # uninformative BrokenPipeError.
                _, stderr_bytes = self.proc.communicate()
                stderr_text = self._decode_tail(stderr_bytes)
                logger.error(
                    "FFmpeg pipe broke mid-render for '%s': %s\n%s",
                    self.output_path,
                    exc,
                    stderr_text,
                )
                self.proc = None  # stop trying to write to a dead process
                # Only the throwaway temp file was ever touched (see
                # __init__) — output_path itself is untouched, so there's
                # nothing to protect there; just clean up our own mess.
                Path(self._temp_path).unlink(missing_ok=True)
                raise RuntimeError(
                    f"FFmpeg process died mid-render while writing '{self.output_path}': "
                    f"{exc}\n--- ffmpeg stderr (tail) ---\n{stderr_text}"
                ) from exc
        elif self._fallback_writer:
            self._fallback_writer.write(frame)
        else:
            raise RuntimeError(
                "No active video writer available (ffmpeg died and no OpenCV fallback configured)."
            )

    def release(self, output_path: str) -> str:
        if self.proc is not None:
            if self.proc.stdin:
                try:
                    self.proc.stdin.close()
                except (BrokenPipeError, OSError):
                    pass  # already dead; communicate() below still reaps it safely

            # [NOTE] [Editor] communicate() instead of wait() — deadlock-safe stderr
            # drain, see module docstring.
            _, stderr_bytes = self.proc.communicate()

            # [NOTE] [Editor] Actually check the exit code. This was previously
            # ignored entirely, so a failed encode looked identical to a
            # successful one to every caller downstream.
            if self.proc.returncode != 0:
                stderr_text = self._decode_tail(stderr_bytes)
                logger.error(
                    "FFmpeg exited %d while producing '%s'\n%s",
                    self.proc.returncode,
                    output_path,
                    stderr_text,
                )
                Path(self._temp_path).unlink(missing_ok=True)
                raise RuntimeError(
                    f"FFmpeg failed (exit {self.proc.returncode}) while producing "
                    f"'{output_path}'.\n--- ffmpeg stderr (tail) ---\n{stderr_text}"
                )
            # The only moment output_path itself is ever touched — an
            # atomic rename (same directory/filesystem, see
            # _make_temp_path) onto the real destination, now that ffmpeg
            # has confirmed the encode actually finished. A process
            # killed at any point before this line leaves whatever was
            # already at output_path completely untouched.
            try:
                _replace_with_retry(self._temp_path, output_path)
            except OSError:
                # Every retry was denied (a persistent file lock outliving
                # the whole retry window) — clean up the fully-encoded
                # temp file before re-raising, same as the two error paths
                # above (broken pipe, nonzero exit) already do, so a
                # failure here doesn't leave an orphaned hidden
                # ".name.<uuid>.tmp.mp4" behind in the output directory.
                Path(self._temp_path).unlink(missing_ok=True)
                raise
            return output_path

        if self._fallback_writer:
            self._fallback_writer.release()

        if output_path.lower().endswith(".mp4") and self._fallback_path:
            temp_mp4 = self._temp_path
            if self._reencode_to_h264(self._fallback_path, temp_mp4):
                _replace_with_retry(temp_mp4, output_path)
                if os.path.exists(self._fallback_path):
                    os.remove(self._fallback_path)
                return output_path
            Path(temp_mp4).unlink(missing_ok=True)

        avi_path = str(Path(output_path).with_suffix(".avi"))
        if self._fallback_path:
            _replace_with_retry(self._fallback_path, avi_path)
        return avi_path

    @staticmethod
    def _decode_tail(stderr_bytes: Optional[bytes]) -> str:
        """Small helper: safely decode + truncate ffmpeg's stderr for logging."""
        if not stderr_bytes:
            return "(no stderr captured)"
        return stderr_bytes[-_STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")

    @staticmethod
    def _reencode_to_h264(src: str, dst: str) -> bool:
        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if ffmpeg_cmd is None:
            return False
        try:
            r = subprocess.run(
                [
                    ffmpeg_cmd,
                    "-y", *tuning.ffmpeg_log_args(),
                    "-i",
                    src,
                    "-vcodec",
                    "libx264",
                    *tuning.ffmpeg_thread_args(),
                    "-crf",
                    "18",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                    dst,
                ],
                capture_output=True,
            )
            if r.returncode != 0:
                logger.error(
                    "H.264 re-encode failed for '%s' -> '%s': %s",
                    src,
                    dst,
                    VideoExporter._decode_tail(r.stderr),
                )
            return r.returncode == 0
        except FileNotFoundError:
            return False

    @staticmethod
    def concat_clips(clip_paths: list[str], output_path: str) -> str:
        """NLE Engine: Stitches multiple atomic .mp4 clips into a seamless master video."""
        if not clip_paths:
            return output_path

        concat_txt = Path(output_path).parent / f"timeline_{uuid.uuid4().hex}.txt"
        with open(concat_txt, "w", encoding="utf-8") as f:
            for path in clip_paths:
                f.write(f"file '{Path(path).resolve().as_posix()}'\n")

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if ffmpeg_cmd:
            # [NOTE] [Editor] Previously ran with stdout/stderr=DEVNULL and NEVER
            # inspected the CompletedProcess result at all — a failed
            # concat (e.g. one clip has mismatched codec params) silently
            # produced no output file (or a truncated one) while the
            # caller happily continued as if it had succeeded. Now
            # captured and checked, matching `concat_from_timeline`'s
            # (already-correct) error handling below.
            result = subprocess.run(
                [
                    ffmpeg_cmd,
                    "-y", *tuning.ffmpeg_log_args(),
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_txt),
                    "-c",
                    "copy",
                    output_path,
                ],
                capture_output=True,
            )
            concat_txt.unlink(missing_ok=True)

            if result.returncode != 0:
                stderr_text = VideoExporter._decode_tail(result.stderr)
                logger.error(
                    "concat_clips failed (exit %d) for -> %s\n%s",
                    result.returncode,
                    output_path,
                    stderr_text,
                )
                raise RuntimeError(
                    f"FFmpeg concat_clips failed (exit {result.returncode}) "
                    f"producing '{output_path}'.\n{stderr_text}"
                )
        else:
            concat_txt.unlink(missing_ok=True)
            raise RuntimeError("FFmpeg binary not found; cannot concatenate clips.")

        return output_path

    @staticmethod
    def _mux_track_for_concat(
        ffmpeg_cmd: str, video_path: Path, audio_path: Optional[str], tmp_dir: Path, index: int,
        audio_offset: float = 0.0, target_size: Optional[Tuple[int, int]] = None,
        target_fps: Optional[float] = None,
        trim_in: float = 0.0, trim_out: Optional[float] = None,
        volume: float = 1.0, muted: bool = False,
        extra_audio: Optional[str] = None, extra_volume: float = 0.5,
        duration: Optional[float] = None,
    ) -> Path:
        """Combines one timeline track's silent video with its own separate
        audio track (see timeline_step.build_timeline — video and audio are
        kept as two independent tracks all the way through the pipeline so
        a frontend NLE can edit them separately) into a single per-segment
        file the final concat step below can stream-copy.

        A track with no audio gets silence generated to match its video's
        own length instead of being left as a bare video stream — the
        concat demuxer's `-c copy` stream-copy requires every segment to
        carry the SAME stream layout, so a mix of audio-bearing and
        audio-less segments would fail or drop audio unpredictably once
        concatenated. `-shortest` is only used for that silence case (an
        `anullsrc` stream is infinite and must be capped to the video's own
        length) — a REAL audio track is deliberately never trimmed to here
        either, matching mux_audio_to_video's own reasoning: this project's
        clips are already sized so their own narration fits inside their
        own video length, so trimming would only ever cut video short.
        """
        has_audio = bool(audio_path and Path(audio_path).exists())
        tmp_out = tmp_dir / f"seg_{index:04d}{video_path.suffix or '.mp4'}"

        # The narration (plus its start delay) can outlast the video: the
        # picture would end while the voice is still speaking, and every clip
        # after it would drift against its sound. Hold the last frame until the
        # voice is done, and a little beyond (tuning.AUDIO_END_HOLD_SECONDS).
        # An editor timeline states each clip's length (as its preview plays it), used as is.
        hold_extra = 0.0
        if has_audio or duration:
            try:
                from services.tts.ttsengine import FFmpegManager

                if duration:
                    needed = duration
                else:
                    needed = (
                        max(0.0, audio_offset)
                        + FFmpegManager.get_media_duration(str(audio_path))
                        + tuning.AUDIO_END_HOLD_SECONDS
                    )
                video_len = FFmpegManager.get_media_duration(str(video_path))
                if trim_out is not None or trim_in > 0:
                    video_len = min(video_len, trim_out if trim_out is not None else video_len) - trim_in
                hold_extra = needed - video_len
            except (RuntimeError, OSError) as exc:
                logger.warning("concat_from_timeline: could not probe track %d for its audio end: %s", index, exc)
            if hold_extra < 0.05:
                hold_extra = 0.0

        # Every segment must have the same picture size: the concat step below
        # stream-copies, and a clip of another size (the 1280x704 intro/outro
        # cards among 1920x1080 clips) would break the joined video. A clip of
        # another size is scaled to fit and letterboxed.
        filters: List[str] = []
        if target_size:
            size = VideoExporter._video_size(video_path)
            if size and size != target_size:
                tw, th = target_size
                filters.append(
                    f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                    f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,setsar=1"
                )
                logger.info("Track %d: %s scaled to %dx%d.", index, f"{size[0]}x{size[1]}", tw, th)
        # ...and the same frame rate: segments at 24/25/30 fps joined by stream
        # copy lose their timing (the video ended minutes before the audio).
        if target_fps:
            clip_fps = VideoExporter._video_fps(video_path)
            if clip_fps and abs(clip_fps - target_fps) > 0.01:
                filters.append(f"fps={target_fps:g}")
                logger.info("Track %d: %.3g fps converted to %g fps.", index, clip_fps, target_fps)
        if hold_extra:
            logger.info("Track %d: holding its last frame %.2fs so the video lasts as long as its audio.", index, hold_extra)
            filters.append(f"tpad=stop_mode=clone:stop_duration={hold_extra:.3f}")

        trimmed = trim_in > 0.01 or trim_out is not None
        cmd = [ffmpeg_cmd, "-y", *tuning.ffmpeg_log_args()]
        if trim_in > 0.01:
            cmd += ["-ss", f"{trim_in:.3f}"]
        if trim_out is not None:
            cmd += ["-t", f"{max(0.1, trim_out - trim_in):.3f}"]
        cmd += ["-i", str(video_path)]
        if has_audio:
            cmd += ["-i", str(Path(audio_path).resolve())]
        else:
            cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
        extra = bool(extra_audio and Path(extra_audio).exists() and extra_volume > 0.001)
        if extra:
            cmd += ["-i", str(Path(extra_audio).resolve())]
            cmd += ["-map", "0:v:0"]
        else:
            cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        if filters or trimmed:
            if filters:
                cmd += ["-vf", ",".join(filters)]
            cmd += [
                "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
            ]
        else:
            cmd += ["-c:v", "copy"]
        cmd += ["-c:a", "aac", "-ar", "44100", "-ac", "2"]
        # The narration starts `audio_offset` seconds into the clip (a leg's
        # silent opening, see services/vdoprocessing/cliptiming.py), so the
        # voice begins with the walk instead of at the first frame. The audio
        # is then padded with silence up to the video's end (-shortest cuts at
        # the video): every segment's audio must last exactly as long as its
        # video, or each later clip's sound starts early in the joined video.
        audio_filters = []
        if has_audio and audio_offset > 0.01:
            delay_ms = int(round(audio_offset * 1000))
            audio_filters.append(f"adelay={delay_ms}|{delay_ms}")
        if has_audio and (muted or abs(volume - 1.0) > 0.01):
            audio_filters.append(f"volume={0.0 if muted else max(0.0, volume):.3f}")
        if has_audio:
            audio_filters.append("apad")
        if extra:
            # Narration (or silence) plus the footage's own sound, mixed under it.
            voice_chain = ",".join(audio_filters) if audio_filters else "anull"
            cmd += [
                "-filter_complex",
                f"[1:a]{voice_chain}[v];[2:a]volume={max(0.0, extra_volume):.3f}[e];"
                f"[v][e]amix=inputs=2:duration=longest:normalize=0,apad[a]",
                "-map", "[a]",
            ]
        elif audio_filters:
            cmd += ["-af", ",".join(audio_filters)]
        if duration:
            cmd += ["-t", f"{duration:.3f}"]
        cmd += ["-shortest", "-video_track_timescale", str(_TIMESCALE)]
        cmd.append(str(tmp_out))

        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        if result.returncode != 0 or not tmp_out.exists():
            logger.error(
                "concat_from_timeline: failed to mux track %d ('%s'), using it unmuxed: %s",
                index, video_path, result.stderr,
            )
            return video_path
        return tmp_out

    @staticmethod
    def _video_fps(path: Path) -> Optional[float]:
        cap = cv2.VideoCapture(str(path))
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        finally:
            cap.release()
        return fps if fps > 0 else None

    @staticmethod
    def _video_size(path: Path) -> Optional[Tuple[int, int]]:
        cap = cv2.VideoCapture(str(path))
        try:
            w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            cap.release()
        return (w, h) if w > 0 and h > 0 else None

    @staticmethod
    def _timeline_size(timeline_data: dict, tracks: list) -> Optional[Tuple[int, int]]:
        """The size the finished video has: the timeline's own resolution when
        it states one, else the size most of its clips already have."""
        res = timeline_data.get("resolution")
        if isinstance(res, dict) and int(res.get("width") or 0) > 0 and int(res.get("height") or 0) > 0:
            return int(res["width"]), int(res["height"])
        sizes = [VideoExporter._video_size(Path(t["file_path"])) for t in tracks]
        sizes = [sz for sz in sizes if sz]
        return max(set(sizes), key=sizes.count) if sizes else None

    @staticmethod
    def _crossfade_pair(
        ffmpeg_cmd: str, first: Path, second: Path, seconds: float, tmp_dir: Path, index: int,
        target_fps: Optional[float] = None,
    ) -> Optional[Path]:
        """Joins two muxed segments with a crossfade of `seconds` (the first
        one dissolves into the second) as ONE re-encoded segment, sized and
        timed like the first. Used where a leg ends on its fullscreen arrival
        photo and the destination's attraction video follows: instead of a
        hard cut from a frozen photo, it dissolves into the video. Returns
        None if it can't be done (the caller then cuts as before)."""
        from services.tts.ttsengine import FFmpegManager

        try:
            first_len = FFmpegManager.get_media_duration(str(first))
            second_len = FFmpegManager.get_media_duration(str(second))
        except (RuntimeError, OSError) as exc:
            logger.warning("crossfade: could not probe '%s'/'%s': %s", first, second, exc)
            return None
        cap = cv2.VideoCapture(str(first))
        width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = target_fps or cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.release()
        # The dissolve runs on EXTRA frames: the first clip's last frame (its
        # photo already at fullscreen) is held for `d` more seconds inside the
        # dissolve only, so the fade starts the instant the photo is fullscreen
        # and there is no visible freeze before it. Never longer than half the
        # second clip.
        d = min(float(seconds), second_len / 2.0)
        if width <= 0 or height <= 0 or d < 0.1:
            return None

        norm = (
            f"fps={fps:.3f},scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=yuv420p"
        )
        graph = (
            f"[0:v]{norm},tpad=stop_mode=clone:stop_duration={d:.3f}[v0];[1:v]{norm}[v1];"
            f"[v0][v1]xfade=transition=fade:duration={d:.3f}:offset={first_len:.3f}[v];"
            f"[0:a]apad=pad_dur={d:.3f}[a0];[a0][1:a]acrossfade=d={d:.3f},apad[a]"
        )
        out = tmp_dir / f"seg_{index:04d}_fade.mp4"
        cmd = [
            ffmpeg_cmd, "-y", *tuning.ffmpeg_log_args(), "-i", str(first), "-i", str(second),
            "-filter_complex", graph, "-map", "[v]", "-map", "[a]",
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            *tuning.ffmpeg_thread_args(),
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            "-shortest", "-video_track_timescale", str(_TIMESCALE), str(out),
        ]
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        if result.returncode != 0 or not out.exists():
            logger.warning("crossfade failed, cutting instead: %s", result.stderr[-400:])
            return None
        return out

    @staticmethod
    def concat_from_timeline(
        timeline_data: dict, output_path: str, save_json_path: Optional[str] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> str:
        """NLE Engine: Stitches atomic clips using strict absolute paths and pre-flight file checks.

        Every clip the pipeline produces stays silent, with its narration
        kept as a separate track in timeline_data (see build_timeline) so a
        frontend editor can edit video and audio independently — this is
        the ONE place they're finally combined, muxing each track's own
        audio onto its video (see _mux_track_for_concat) right before
        concatenating, rather than baking audio into clips earlier in the
        pipeline where it could no longer be edited separately.
        """
        # 1. Save the timeline.json file to the disk
        if save_json_path:
            with open(save_json_path, "w", encoding="utf-8") as f:
                json.dump(timeline_data, f, indent=2, ensure_ascii=False)

        tracks = timeline_data.get("video_tracks", [])
        if not tracks:
            raise ValueError("Timeline data has no 'video_tracks' to stitch.")

        # [NOTE] [Editor] Run the strict pre-flight check BEFORE opening any files —
        # catching a missing clip early gives a clear error instead of a
        # partially-built concat manifest pointing at a file that doesn't exist.
        for track in tracks:
            clip_path = Path(track["file_path"]).resolve()
            if not clip_path.exists():
                raise FileNotFoundError(
                    f"Missing atomic clip! Cannot compile video because this file is missing: {clip_path}"
                )

        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if not ffmpeg_cmd:
            raise RuntimeError("FFmpeg binary not found.")

        tmp_dir = Path(tempfile.mkdtemp(prefix="navivi_concat_"))
        target_size = VideoExporter._timeline_size(timeline_data, tracks)
        target_fps = float(timeline_data.get("fps") or 30)

        # Percent of the export each step takes, from a timed real export (clips ~25%,
        # crossfades ~22%, music ~1%, subtitle burn ~50%), so the bar moves at an even pace.
        report = on_progress or (lambda _pct: None)
        burning = bool(VideoExporter._burn_cues(timeline_data))
        mux_end, join_end, music_end = (26.0, 49.0, 50.0) if burning else (53.0, 97.0, 99.0)
        weights = [float(t.get("duration") or 0.0) or 1.0 for t in tracks]
        report(0.0)
        try:
            muxed_paths: List[Path] = []
            for i, track in enumerate(tracks):
                muxed_paths.append(VideoExporter._mux_track_for_concat(
                    ffmpeg_cmd, Path(track["file_path"]).resolve(), track.get("audio_path"), tmp_dir, i,
                    audio_offset=float(track.get("audio_offset") or 0.0), target_size=target_size,
                    target_fps=target_fps,
                    trim_in=float(track.get("trim_in") or 0.0),
                    trim_out=float(track["trim_out"]) if track.get("trim_out") else None,
                    volume=float(track.get("volume", 1.0)), muted=bool(track.get("muted")),
                    extra_audio=track.get("extra_audio_path"),
                    extra_volume=float(track.get("extra_audio_volume") if track.get("extra_audio_volume") is not None else 0.5),
                    duration=float(track["duration"]) if track.get("duration") else None,
                ))
                report(mux_end * sum(weights[: i + 1]) / sum(weights))

            # A track marked fade_into_next_seconds dissolves into the track
            # after it (see timeline_step): the pair becomes one segment.
            joined_paths: List[Path] = []
            skip_next = False
            fades = [i for i, t in enumerate(tracks[:-1]) if float(t.get("fade_into_next_seconds") or 0.0) > 0]
            for i, muxed in enumerate(muxed_paths):
                if skip_next:
                    skip_next = False
                    continue
                fade = float(tracks[i].get("fade_into_next_seconds") or 0.0)
                if fade > 0 and i + 1 < len(muxed_paths):
                    merged = VideoExporter._crossfade_pair(
                        ffmpeg_cmd, muxed, muxed_paths[i + 1], fade, tmp_dir, i, target_fps=target_fps
                    )
                    done = sum(1 for k in fades if k <= i)
                    report(mux_end + (join_end - mux_end) * done / max(1, len(fades)))
                    if merged is not None:
                        joined_paths.append(merged)
                        skip_next = True
                        continue
                joined_paths.append(muxed)
            muxed_paths = joined_paths

            concat_txt = output_dir / f"timeline_{uuid.uuid4().hex}.txt"

            # 2. Write Absolute Paths
            with open(concat_txt, "w", encoding="utf-8") as f:
                for clip_path in muxed_paths:
                    f.write(f"file 'file:{clip_path.resolve().as_posix()}'\n")

            # 3. Execute the seamless stitch
            result = subprocess.run(
                [
                    ffmpeg_cmd,
                    "-y", *tuning.ffmpeg_log_args(),
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_txt),
                    "-c",
                    "copy",
                    str(output_path),
                ],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )

            # Clean up the temporary FFmpeg text file
            concat_txt.unlink(missing_ok=True)

            # 4. Strict Post-flight Check
            if result.returncode != 0:
                logger.error("concat_from_timeline failed: %s", result.stderr)
                raise RuntimeError(f"FFmpeg concat failed: {result.stderr}")

            final_file = Path(output_path)
            if not final_file.exists() or final_file.stat().st_size == 0:
                raise RuntimeError(
                    f"FFmpeg reported success, but the output file is missing or 0 bytes! STDERR: {result.stderr}"
                )

            report(join_end)
            VideoExporter._finish_timeline_output(
                ffmpeg_cmd, timeline_data, output_path, tmp_dir,
                on_progress=lambda f: report(music_end + (100.0 - music_end) * f),
            )
            report(100.0)
            return output_path
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _burn_cues(timeline_data: dict) -> list:
        if not timeline_data.get("burn_subtitles", True):
            return []
        return [c for c in timeline_data.get("subtitles") or [] if str(c.get("text", "")).strip()]

    @staticmethod
    def _finish_timeline_output(
        ffmpeg_cmd: str, timeline_data: dict, output_path: str, tmp_dir: Path,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> None:
        """Music bed and burned subtitles, applied to the joined video in place."""
        music = timeline_data.get("music") or {}
        music_path = music.get("path")
        if music_path and Path(music_path).exists():
            mixed = tmp_dir / "with_music.mp4"
            volume = max(0.0, float(music.get("volume", 0.25)))
            result = subprocess.run(
                [
                    ffmpeg_cmd, "-y", *tuning.ffmpeg_log_args(), "-i", str(output_path),
                    "-stream_loop", "-1", "-i", str(music_path),
                    "-filter_complex",
                    f"[1:a]volume={volume:.3f}[m];[0:a][m]amix=inputs=2:duration=first:normalize=0[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-ar", "44100", "-ac", "2",
                    "-shortest", str(mixed),
                ],
                capture_output=True, encoding="utf-8", errors="replace",
            )
            if result.returncode == 0 and mixed.exists():
                _replace_with_retry(str(mixed), str(output_path))
            else:
                logger.warning("music bed skipped: %s", result.stderr[-400:])

        cues = VideoExporter._burn_cues(timeline_data)
        # Text-track items (e.g. the intro title) burn even when subtitles are off.
        texts = [
            x for x in timeline_data.get("texts") or []
            if str((x.get("title") or {}).get("text", "")).strip()
            or str((x.get("subtitle") or {}).get("text", "")).strip()
        ]
        if cues or texts:
            ass = write_caption_ass(
                cues, timeline_data.get("caption_style"), VideoExporter._video_size(Path(output_path)),
                tmp_dir / "subtitles.ass", texts=texts,
            )
            burned = tmp_dir / "with_subtitles.mp4"
            try:
                VideoExporter.burn_subtitles(str(output_path), str(ass), str(burned), on_progress=on_progress)
                _replace_with_retry(str(burned), str(output_path))
            except Exception as exc:  # the stitched video is still good without them
                logger.warning("subtitle burn skipped: %s", exc)

    @staticmethod
    def cues_to_srt(cues: list) -> str:
        blocks = []
        for i, cue in enumerate(sorted(cues, key=lambda c: float(c["start"])), 1):
            start = VideoExporter._format_srt_timestamp(float(cue["start"]))
            end = VideoExporter._format_srt_timestamp(float(cue["end"]))
            blocks.append(f"{i}\n{start} --> {end}\n{str(cue['text']).strip()}\n")
        return "\n".join(blocks)

    @staticmethod
    def burn_subtitles(
        input_video_path: str, subtitle_file_path: str, output_video_path: str,
        style: Optional[SubtitleStyle] = None,
        on_progress: Optional[Callable[[float], None]] = None,
    ) -> str:
        """NLE Engine: Burns an .srt or .ass subtitle file permanently into a video track (Cross-Platform Safe)."""
        video_path = Path(input_video_path)
        sub_path = Path(subtitle_file_path)

        if not video_path.exists():
            raise FileNotFoundError(
                f"Cannot burn subtitles: Video missing {video_path}"
            )
        if not sub_path.exists():
            raise FileNotFoundError(
                f"Cannot burn subtitles: Subtitle file missing {sub_path}"
            )

        # Ensure output directory exists
        out_path = Path(output_video_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if not ffmpeg_cmd:
            raise RuntimeError("FFmpeg binary not found.")

        # [HACK] [Editor] FFmpeg's subtitle filter crashes on Windows absolute paths (e.g., C:\).
        # We must format the path with forward slashes and escape the colon for the filter.
        # e.g., 'C\:/Users/...' -> safely parsed by the FFmpeg filter graph.
        safe_sub_path = sub_path.as_posix().replace(":", "\\:")
        sub_filter = f"subtitles='{safe_sub_path}'"
        if style:
            sub_filter = f"subtitles=filename='{safe_sub_path}':force_style='{style.to_force_style()}'"

        cmd = [
            ffmpeg_cmd,
            "-y", *tuning.ffmpeg_log_args(),
            "-i",
            str(video_path),
            "-vf",
            sub_filter,
            *tuning.ffmpeg_thread_args(),
            "-c:a",
            "copy",  # Copy the audio without re-encoding it
            str(out_path),
        ]
        if on_progress:
            result = _run_with_progress(cmd, str(video_path), on_progress)
        else:
            result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")

        if result.returncode != 0:
            logger.error("burn_subtitles failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg subtitle burn failed: {result.stderr}")

        return str(out_path)

    @staticmethod
    def upscale_video(
        input_video_path: str,
        output_video_path: str,
        target_width: int = 1920,
        target_height: int = 1080,
    ) -> str:
        """Scales a clip up to target_width x target_height via ffmpeg's CPU
        lanczos filter (no GPU/VRAM cost — unlike ComfyUI's own upscaler,
        this doesn't compete with attraction-video generation for the 8GB
        VRAM budget). Used to bring ComfyUI attraction clips (rendered at a
        lower resolution to fit VRAM) up to match the 1920x1080 map/waypoint
        clips before they're combined, since nothing else in the pipeline
        reconciles mismatched clip resolutions.
        """
        # [NOTE] [Editor] CPU lanczos scale keeps this off the GPU so it doesn't
        # contend with ComfyUI's attraction-video generation for the 8GB VRAM budget.
        video_path = Path(input_video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Cannot upscale: video missing {video_path}")

        out_path = Path(output_video_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if not ffmpeg_cmd:
            raise RuntimeError("FFmpeg binary not found.")

        result = subprocess.run(
            [
                ffmpeg_cmd,
                "-y", *tuning.ffmpeg_log_args(),
                "-i",
                str(video_path),
                "-vf",
                f"scale={target_width}:{target_height}:flags=lanczos",
                *tuning.ffmpeg_thread_args(),
                "-c:a",
                "copy",
                str(out_path),
            ],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
        )

        if result.returncode != 0:
            logger.error("upscale_video failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg upscale failed: {result.stderr}")

        return str(out_path)

    # [Core/Animation] Burns a persistent corner label (e.g. an attraction's place name) into a video
    @staticmethod
    def burn_static_label(
        input_video_path: str,
        text: str,
        output_video_path: str,
        style: Optional[SubtitleStyle] = None,
    ) -> str:
        """Burns a single always-on text label (e.g. an attraction clip's
        place name) into a video for its entire duration. Reuses the same
        subtitles-filter approach as burn_subtitles/introclip's title card —
        one big single-cue .srt spanning the whole clip instead of many
        timed lines — rather than introducing a second burn-in mechanism."""
        video_path = Path(input_video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Cannot burn label: video missing {video_path}")
        if not text:
            raise ValueError("Cannot burn an empty label.")

        out_path = Path(output_video_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if not ffmpeg_cmd:
            raise RuntimeError("FFmpeg binary not found.")

        from services.tts.ttsengine import FFmpegManager

        duration = FFmpegManager.get_media_duration(str(video_path))

        style = style or SubtitleStyle(
            font_size=tuning.ATTRACTION_LABEL_FONT_SIZE,
            bold=True,
            alignment=5,  # old-SSA top-left — see SubtitleStyle.alignment's note
            outline=tuning.ATTRACTION_LABEL_OUTLINE,
            shadow=1.0,
            margin_v=tuning.ATTRACTION_LABEL_MARGIN_TOP,
            margin_l=tuning.ATTRACTION_LABEL_MARGIN_LEFT,
        )

        srt_path = out_path.parent / f".label_{uuid.uuid4().hex[:8]}.srt"
        end_ts = VideoExporter._format_srt_timestamp(duration)
        srt_path.write_text(f"1\n00:00:00,000 --> {end_ts}\n{text}\n", encoding="utf-8")

        # [HACK] [Subtitle] Same absolute/forward-slashed/colon-escaped path
        # normalization burn_subtitles uses — libass's own escaping rules.
        escaped_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", r"\:")

        try:
            result = subprocess.run(
                [
                    ffmpeg_cmd, "-y", *tuning.ffmpeg_log_args(),
                    "-i", str(video_path),
                    "-vf",
                    f"subtitles=filename='{escaped_srt}':force_style='{style.to_force_style()}'",
                    *tuning.ffmpeg_thread_args(),
                    "-c:a", "copy",
                    str(out_path),
                ],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
            )
        finally:
            srt_path.unlink(missing_ok=True)

        if result.returncode != 0:
            logger.error("burn_static_label failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg label burn failed: {result.stderr}")

        return str(out_path)

    # [Util] Formats a timestamp in seconds to the SRT timestamp format (HH:MM:SS,mmm)
    @staticmethod
    def _format_srt_timestamp(seconds: float) -> str:
        total_ms = max(0, int(round(seconds * 1000)))
        hours, rem_ms = divmod(total_ms, 3_600_000)
        minutes, rem_ms = divmod(rem_ms, 60_000)
        secs, ms = divmod(rem_ms, 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"

    # [Core/Animation] Fuses duration-fit + upscale + label burn into one ffmpeg pass
    @staticmethod
    def finalize_clip(
        input_video_path: str,
        output_video_path: str,
        *,
        trim_to: Optional[float] = None,
        hold_to: Optional[float] = None,
        scale_to: Optional[Tuple[int, int]] = None,
        sharpen: bool = False,
        label_text: Optional[str] = None,
        label_style: Optional[SubtitleStyle] = None,
    ) -> str:
        """Combines what used to be up to three sequential ffmpeg re-encodes
        — trim_video_duration, upscale_video, and burn_static_label, each a
        full decode+encode pass over the same clip — into a single filter
        graph and a single encode. Pass only the stages actually needed;
        omitting all of them is just a (still single-pass) re-encode/copy.

        trim_to and hold_to are mutually exclusive: trim_to hard-cuts the
        tail (same as trim_video_duration); hold_to plays the clip at its
        natural speed and then freezes/clones the final frame (ffmpeg's
        tpad) to pad out the remaining gap — motion stays at normal speed,
        only the padding is static. There's deliberately no time-scaling
        (setpts) option here — stretching the WHOLE clip in slow motion
        would visibly exaggerate any motion instability in a generated
        clip, so an overlong/underlong clip is always trimmed or
        freeze-held, never sped up or slowed down. scale_to applies a
        lanczos resize; sharpen adds a mild unsharp pass right after it to
        claw back some of the perceived softness a lanczos upscale
        introduces. label_text burns a full-duration top-left caption (see
        burn_static_label) using the SAME output duration as trim_to/
        hold_to, so the label's .srt cue doesn't have to be probed against
        a not-yet-written file.
        """
        if trim_to is not None and hold_to is not None:
            raise ValueError(
                "finalize_clip: pass at most one of trim_to/hold_to."
            )

        video_path = Path(input_video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"Cannot finalize clip: video missing {video_path}")

        out_path = Path(output_video_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        ffmpeg_cmd = VideoExporter.resolve_ffmpeg()
        if not ffmpeg_cmd:
            raise RuntimeError("FFmpeg binary not found.")

        from services.tts.ttsengine import FFmpegManager

        vf_parts: List[str] = []

        if hold_to is not None:
            current_duration = FFmpegManager.get_media_duration(str(video_path))
            if current_duration <= 0:
                raise RuntimeError(
                    f"ffprobe reported non-positive duration for '{video_path}'"
                )
            pad_seconds = hold_to - current_duration
            if pad_seconds > 0:
                vf_parts.append(f"tpad=stop_mode=clone:stop_duration={pad_seconds:.3f}")

        if scale_to is not None:
            target_width, target_height = scale_to
            vf_parts.append(f"scale={target_width}:{target_height}:flags=lanczos")
            if sharpen:
                # Mild luma-only unsharp mask — just enough to counter a
                # lanczos upscale's softening, not a stylistic sharpen.
                vf_parts.append("unsharp=5:5:0.5:5:5:0.0")

        srt_path: Optional[Path] = None
        if label_text:
            output_duration = trim_to or hold_to
            if output_duration is None:
                output_duration = FFmpegManager.get_media_duration(str(video_path))

            style = label_style or SubtitleStyle(
                font_size=tuning.ATTRACTION_LABEL_FONT_SIZE,
                bold=True,
                alignment=5,  # old-SSA top-left — see SubtitleStyle.alignment's note
                outline=tuning.ATTRACTION_LABEL_OUTLINE,
                shadow=1.0,
                margin_v=tuning.ATTRACTION_LABEL_MARGIN_TOP,
                margin_l=tuning.ATTRACTION_LABEL_MARGIN_LEFT,
            )
            srt_path = out_path.parent / f".label_{uuid.uuid4().hex[:8]}.srt"
            end_ts = VideoExporter._format_srt_timestamp(output_duration)
            srt_path.write_text(
                f"1\n00:00:00,000 --> {end_ts}\n{label_text}\n", encoding="utf-8"
            )
            escaped_srt = str(srt_path.resolve()).replace("\\", "/").replace(":", r"\:")
            vf_parts.append(
                f"subtitles=filename='{escaped_srt}':force_style='{style.to_force_style()}'"
            )

        cmd = [ffmpeg_cmd, "-y", *tuning.ffmpeg_log_args(), "-i", str(video_path)]
        if vf_parts:
            cmd += ["-vf", ",".join(vf_parts)]
        if trim_to is not None:
            cmd += ["-t", f"{trim_to:.3f}"]
        cmd += [
            "-c:v", "libx264", *tuning.ffmpeg_thread_args(),
            "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            str(out_path),
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, encoding="utf-8", errors="replace"
            )
        finally:
            if srt_path is not None:
                srt_path.unlink(missing_ok=True)

        if result.returncode != 0:
            logger.error("finalize_clip failed: %s", result.stderr)
            raise RuntimeError(f"FFmpeg finalize_clip failed: {result.stderr}")

        return str(out_path)