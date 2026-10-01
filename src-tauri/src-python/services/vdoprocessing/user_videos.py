"""A waypoint's own footage as its attraction clip, in place of an AI-animated photo.

The user's videos are normalised (silent, H.264), then fitted to the narration by the same
machinery photo clips use (hold the last frame / trim, scale to the project size, place label).
With "keep its sound" on, the footage's audio is written beside the clip as `<clip>.orig.wav`
(same length as the clip); timeline_step lists it as the segment's extra audio and the exporter
mixes it under the narration. Sound is off unless asked for.
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional

from services.logger.logger import setup_logger
from services.vdoprocessing.vdoexporter import VideoExporter
from services.vdoprocessing.videopipeline.helpers import output_is_valid

logger = setup_logger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
SIDECAR_SUFFIX = ".orig.wav"


def original_sound_path(video_path: str) -> Path:
    return Path(video_path).with_suffix(SIDECAR_SUFFIX)


def _fingerprint(clips: List[str], keep: List[bool], target: float, label: Optional[str]) -> dict:
    files = []
    for path in clips:
        stat = os.stat(path)
        files.append([path, stat.st_size, int(stat.st_mtime)])
    return {"files": files, "keep": keep, "target": round(float(target), 2), "label": label}


def _ffmpeg() -> str:
    cmd = VideoExporter.resolve_ffmpeg()
    if not cmd:
        raise RuntimeError("FFmpeg binary not found.")
    return cmd


def _normalise(src: str, dst: str) -> bool:
    result = subprocess.run(
        [
            _ffmpeg(), "-y", "-loglevel", "error", "-i", src, "-an",
            "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", dst,
        ],
        capture_output=True, encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        logger.error("Could not read user video %s: %s", src, result.stderr[-300:])
    return result.returncode == 0 and output_is_valid(dst)


def _audio_of(src: str, length: float, dst: str) -> None:
    """`length` seconds of src's sound (padded with silence), or plain silence if it has none."""
    base = [_ffmpeg(), "-y", "-loglevel", "error"]
    tail = ["-t", f"{length:.3f}", "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", dst]
    with_sound = subprocess.run([*base, "-i", src, "-vn", "-af", "apad", *tail], capture_output=True)
    if with_sound.returncode != 0 or not os.path.exists(dst):
        subprocess.run(
            [*base, "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100", *tail],
            capture_output=True, check=True,
        )


def _silence(length: float, dst: str) -> None:
    subprocess.run(
        [
            _ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-t", f"{length:.3f}", "-c:a", "pcm_s16le", dst,
        ],
        capture_output=True, check=True,
    )


def _write_original_sound(clips: List[str], raws: List[str], keep: List[bool], target: float, final: str, out: Path) -> None:
    from services.tts.ttsengine import FFmpegManager

    final_len = FFmpegManager.get_media_duration(final)
    with tempfile.TemporaryDirectory(prefix="navivi_orig_") as tmp:
        parts = []
        for i, (src, raw) in enumerate(zip(clips, raws)):
            length = target / len(clips) if target > 0 else FFmpegManager.get_media_duration(raw)
            part = os.path.join(tmp, f"p{i}.wav")
            (_audio_of if keep[i] else lambda _s, n, d: _silence(n, d))(src, length, part)
            parts.append(part)
        listing = os.path.join(tmp, "parts.txt")
        with open(listing, "w", encoding="utf-8") as f:
            f.writelines(f"file '{Path(p).as_posix()}'\n" for p in parts)
        joined = os.path.join(tmp, "joined.wav")
        subprocess.run(
            [_ffmpeg(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", joined],
            capture_output=True, check=True,
        )
        subprocess.run(
            [
                _ffmpeg(), "-y", "-loglevel", "error", "-i", joined, "-af", "apad", "-t", f"{final_len:.3f}",
                "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(out),
            ],
            capture_output=True, check=True,
        )


def process_user_videos(
    generator,
    videos: List[str],
    keep_sound: List[bool],
    target_audio_duration: float,
    output_filename: str,
    place_label: Optional[str] = None,
    force: bool = False,
) -> Optional[str]:
    """Builds the attraction clip `output_filename` from the user's own videos. None if none can be read."""
    pairs = [(v, bool(keep_sound[i]) if i < len(keep_sound) else False) for i, v in enumerate(videos) if v and os.path.exists(v)]
    if not pairs:
        return None
    clips = [p for p, _ in pairs]
    keep = [k for _, k in pairs]

    final_path = generator.output_dir / output_filename
    sidecar = original_sound_path(str(final_path))
    stamp = final_path.with_suffix(".src.json")
    fingerprint = _fingerprint(clips, keep, target_audio_duration, place_label)

    if not force and output_is_valid(final_path):
        try:
            if json.loads(stamp.read_text(encoding="utf-8")) == fingerprint:
                logger.info("User video clip unchanged - skipping: %s", final_path)
                return str(final_path)
        except (OSError, ValueError):
            pass

    generator._clear_stale_outputs(output_filename)
    for stale in (sidecar, stamp):
        stale.unlink(missing_ok=True)

    stem = Path(output_filename).stem
    raws: List[str] = []
    used: List[str] = []
    used_keep: List[bool] = []
    try:
        for i, src in enumerate(clips):
            raw = str(generator.output_dir / f"raw_{stem}_{i:02d}.mp4")
            if _normalise(src, raw):
                raws.append(raw)
                used.append(src)
                used_keep.append(keep[i])
        if not raws:
            return None

        if len(raws) > 1:
            result = generator._combine_clips(raws, ["none"] * len(raws), target_audio_duration, output_filename, place_label)
        else:
            result = generator._fit_and_finalize(
                raws[0], target_audio_duration, output_filename, generator._AUDIO_DURATION_TOLERANCE_SECONDS,
                place_label=place_label, camera_pan="none",
            )
        if result and any(used_keep):
            _write_original_sound(used, raws, used_keep, target_audio_duration, result, sidecar)
        if result:
            stamp.write_text(json.dumps(fingerprint), encoding="utf-8")
        return result
    finally:
        for raw in raws:
            try:
                os.remove(raw)
            except OSError:
                pass
