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
from typing import List, Optional, Tuple

from services.ffconcat import concat_entry
from services.logger.logger import setup_logger
from services.vdoprocessing.vdoexporter import VideoExporter
from services.vdoprocessing.videopipeline.helpers import output_is_valid

logger = setup_logger(__name__)

SIDECAR_SUFFIX = ".orig.wav"


def photos_kept(waypoint: dict) -> List[str]:
    """The stop's photos that still get a clip of their own: each of its videos takes the place of one, from the
    first. One video and three photos = the footage, then photos 2 and 3."""
    images = waypoint.get("images") or waypoint.get("popup_image") or []
    if isinstance(images, str):
        images = [images]
    return [p for p in images if p][len([v for v in waypoint.get("videos") or [] if v]):]


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


def normalise_video(src: str, dst: str) -> bool:
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


def write_original_sound(parts: List[Tuple[Optional[str], float]], final: str, out: Path) -> None:
    """`parts` = (video whose sound to keep, or None for silence; seconds), in the clip's own order.
    Written to `final`'s length, so the exporter can mix it straight under the narration."""
    from services.tts.ttsengine import FFmpegManager

    final_len = FFmpegManager.get_media_duration(final)
    with tempfile.TemporaryDirectory(prefix="navivi_orig_") as tmp:
        pieces = []
        for i, (src, length) in enumerate(parts):
            piece = os.path.join(tmp, f"p{i}.wav")
            if src:
                _audio_of(src, length, piece)
            else:
                _silence(length, piece)
            pieces.append(piece)
        listing = os.path.join(tmp, "parts.txt")
        with open(listing, "w", encoding="utf-8") as f:
            f.writelines(concat_entry(p) for p in pieces)
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
            if normalise_video(src, raw):
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
            from services.tts.ttsengine import FFmpegManager

            share = target_audio_duration / len(raws) if target_audio_duration > 0 else None
            write_original_sound(
                [(src if used_keep[i] else None, share if share else FFmpegManager.get_media_duration(raws[i]))
                 for i, src in enumerate(used)],
                result, sidecar,
            )
        if result:
            stamp.write_text(json.dumps(fingerprint), encoding="utf-8")
        return result
    finally:
        for raw in raws:
            try:
                os.remove(raw)
            except OSError:
                pass
