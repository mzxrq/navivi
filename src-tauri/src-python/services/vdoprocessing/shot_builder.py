"""An attraction clip as a few short Wan shots, each started from the original
photo with a different camera move (tuning.ATTRACTION_SHOT_MOVES), each cut
where clip_qc finds it stops being the photo, easing to a stop before a hard
cut. Whatever narration is left is a depth-parallax move over the photo.

Every shot starts from the photo, so nothing drifts from shot to shot the way
last-frame chaining did.
"""

import math
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np

from services import tuning
from services.logger.logger import setup_logger
from services.vdoprocessing import clip_qc
from services.vdoprocessing.camera_pan import normalize_camera_pan

logger = setup_logger("ShotBuilder")


def shot_moves(preset: str) -> List[str]:
    moves = []
    for move in tuning.ATTRACTION_SHOT_MOVES:
        move = normalize_camera_pan(preset) if move == "preset" else move
        if move and move not in moves:
            moves.append(move)
    return moves[: tuning.ATTRACTION_MAX_WAN_SHOTS]


def settle(frames: List[np.ndarray], fps: float, max_frames: Optional[int] = None) -> List[np.ndarray]:
    """frames whose last ATTRACTION_SHOT_SETTLE_SECONDS play over twice as
    long, slowing to a stop (frames blended), then a short hold. Trimmed from
    the end first if the result would exceed max_frames."""
    src = max(1, round(tuning.ATTRACTION_SHOT_SETTLE_SECONDS * fps))
    hold = round(tuning.ATTRACTION_SHOT_HOLD_SECONDS * fps)
    if max_frames is not None:
        # total = (n - src) + 2*src + hold
        n = max(src + 1, min(len(frames), max_frames - src - hold))
        frames = frames[:n]
    src = min(src, len(frames) - 1)
    head, tail = frames[: len(frames) - src - 1], frames[len(frames) - src - 1:]
    out = list(head)
    steps = 2 * src
    for i in range(steps):
        u = (i + 1) / steps
        pos = src * (1 - (1 - u) ** 2)  # starts at full speed, ends at zero
        a = int(math.floor(pos))
        b = min(a + 1, src)
        w = pos - a
        out.append((tail[a] * (1 - w) + tail[b] * w).astype(np.uint8) if w > 1e-3 else tail[a])
    out.extend([tail[-1]] * hold)
    if max_frames is not None:
        out = out[:max_frames]
    return out


def _write(frames: List[np.ndarray], fps: float, path: str) -> None:
    from services.tts.ttsengine import FFmpegManager

    if not frames:
        raise ValueError("There are no frames to write.")
    h, w = frames[0].shape[:2]
    # [NOTE] ffmpeg's messages go to a file, not a pipe nobody reads while frames are being written: a flood of warnings
    # would fill the pipe and hang both processes.
    err = tempfile.TemporaryFile()
    proc = subprocess.Popen(
        [
            FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_pipe_log_args(),
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "-",
            "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "16", "-preset", "fast",
            "-pix_fmt", "yuv420p", path,
        ],
        stdin=subprocess.PIPE, stderr=err,
    )
    try:
        for frame in frames:
            proc.stdin.write(frame.tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            err.seek(0)
            raise RuntimeError(err.read().decode("utf-8", "replace"))
    except Exception:
        proc.kill()
        raise
    finally:
        err.close()


def concat_clips(paths: List[str], output_path: str, width: int, height: int, fps: float) -> None:
    """Joins clips with hard cuts, re-encoded at one size/fps."""
    from services.tts.ttsengine import FFmpegManager

    if len(paths) == 1:
        inputs, graph = ["-i", paths[0]], (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
            f"fps={fps},setsar=1,format=yuv420p[out]"
        )
    else:
        inputs, chains = [], []
        for i, path in enumerate(paths):
            inputs += ["-i", path]
            chains.append(
                f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
                f"fps={fps},setsar=1,format=yuv420p[v{i}]"
            )
        graph = ";".join(chains) + ";" + "".join(f"[v{i}]" for i in range(len(paths)))
        graph += f"concat=n={len(paths)}:v=1:a=0[out]"
    result = subprocess.run(
        [FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_log_args(), *inputs,
         "-filter_complex", graph, "-map", "[out]",
         "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast",
         "-pix_fmt", "yuv420p", output_path],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"Joining clips failed: {result.stderr.strip()}")


def _wan_shot(photo_path: str, path: str, move: str, seconds: float) -> None:
    from services.gpu_cooldown import wait_for_gpu_cooldown
    from services.vdoprocessing.color_match import match_clip_to_photo
    from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

    wait_for_gpu_cooldown(f"Wan shot '{move}' for {Path(photo_path).name}")
    ComfyUII2VClient().generate_clip(photo_path, path, seconds, camera_pan_hint=move)
    match_clip_to_photo(path, photo_path)


def build_shots(
    photo_path: str,
    output_path: str,
    duration_sec: float,
    preset,
    wan_shot: Callable[[str, str, str, float], None] = _wan_shot,
    parallax: Optional[Callable[..., str]] = None,
) -> str:
    """Writes the clip to output_path (1920x1080, tuning.COMFYUI_FPS) lasting
    duration_sec. Raises only if nothing at all could be made."""
    if parallax is None:
        from services.vdoprocessing.parallax_generator import generate_parallax_clip as parallax
    from services.vdoprocessing.parallax_generator import OUT_H, OUT_W

    fps = float(tuning.COMFYUI_FPS)
    total = max(1, round(duration_sec * fps))
    min_frames = round(tuning.ATTRACTION_MIN_SHOT_SECONDS * fps)
    segment = tuning.COMFYUI_MAX_FRAMES / tuning.COMFYUI_GEN_FPS
    photo = clip_qc.read_image(photo_path)
    work = Path(output_path).parent / f".shots_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    pieces: List[str] = []
    covered = 0
    try:
        for k, move in enumerate(shot_moves(preset)):
            left = total - covered
            if left < min_frames:
                break
            raw = str(work / f"wan{k}.mp4")
            try:
                wan_shot(photo_path, raw, move, min(segment, left / fps + 1.0))
            except Exception as exc:
                logger.warning("Wan shot '%s' failed (%s: %s) - no more Wan shots.", move, type(exc).__name__, exc)
                break
            frames = clip_qc.read_frames(raw)
            bad = clip_qc.first_bad_frame(frames, photo, move in clip_qc.REVEALING_MOVES) if photo is not None else 0
            keep = len(frames) if bad is None else max(0, bad - tuning.ATTRACTION_QC_BACKOFF_FRAMES)
            if keep < min_frames:
                logger.info("Shot %d '%s': only %d clean frames - dropped.", k + 1, move, keep)
                continue
            shot = settle(frames[:keep], fps, left)
            path = str(work / f"shot{k}.mp4")
            _write(shot, fps, path)
            pieces.append(path)
            covered += len(shot)
            logger.info(
                "Shot %d '%s': kept %d of %d frames -> %.1fs with its settle.",
                k + 1, move, keep, len(frames), len(shot) / fps,
            )

        left = total - covered
        if left >= round(0.5 * fps) or not pieces:
            path = str(work / "parallax.mp4")
            parallax(photo_path, path, max(left, 1) / fps, preset)
            pieces.append(path)
            logger.info("Parallax fill: %.1fs.", max(left, 1) / fps)

        concat_clips(pieces, output_path, OUT_W, OUT_H, fps)
        return output_path
    finally:
        shutil.rmtree(work, ignore_errors=True)
