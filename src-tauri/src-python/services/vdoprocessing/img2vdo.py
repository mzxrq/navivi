"""
Image-to-Video Service for Attractions
----------------------------------------------------------------------------
Handles image-to-video generation (ComfyUI/Wan2.2, falling back to local
AI-outpaint + pan on failure), multi-image list detection, concatenation
via VideoEditor, and audio synchronization.
----------------------------------------------------------------------------
"""

import hashlib
import math
import os
import json
import shutil
import uuid
from pathlib import Path
from typing import Final, List, Optional, Tuple, Union

from services import tuning
from services.vdoprocessing.vdoeditor import VideoEditor
from services.vdoprocessing.vdoexporter import VideoExporter
from services.config.job_config import JobConfigManager
from services.logger.logger import setup_logger
from services.vdoprocessing.videopipeline.helpers import output_is_valid, project_attraction_video_dir

# Logging configuration
logger = setup_logger("AttractionVideoGenerator")


# [NOTE] [Animation] AttractionVideoGenerator manages Image-to-Video generation and synchronization for attractions.
class AttractionVideoGenerator:
    """Manages Image-to-Video generation and synchronization for attractions."""

    # [Config] Initialize with JobConfigManager
    def __init__(self, job_config: Optional[JobConfigManager] = None):
        self.config = job_config or JobConfigManager()
        self.editor = VideoEditor(job_config=self.config)

        # Route outputs to the project's attraction video subfolder
        base_dir = Path(self.config.get("directory_path", "assets"))
        self.output_dir = project_attraction_video_dir(base_dir).resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # [NOTE] [Config] Matches mapfetcher.py's MapFetcher.fetch_image/process_residential_sequence
    # default output_size — the resolution the map/waypoint clips actually
    # render at. ComfyUI attraction clips are generated smaller (currently
    # 1280x704) to fit the 8GB VRAM budget; upscaling here keeps every clip
    # the same resolution before subtitle burning, since nothing downstream
    # in the pipeline reconciles mismatched clip sizes.
    _TARGET_WIDTH: Final[int] = 1920
    _TARGET_HEIGHT: Final[int] = 1080

    # [NOTE] [Editor] Audio/video duration mismatch tolerance. Multi-image waypoints
    # concatenate several fixed-length ComfyUI clips together (e.g. 2 x 7s
    # = 14s), which can run far past a short narration — left uncorrected,
    # that mismatch reaches the downstream timeline/NLE step, which pads
    # the gap by freezing on the last frame until the narration ends.
    # Single-image waypoints get the same general tolerance; multi-image
    # ones get a tighter overshoot cap since concatenation compounds error.
    _AUDIO_DURATION_TOLERANCE_SECONDS: Final[float] = 3.0
    _MULTI_IMAGE_OVERSHOOT_TOLERANCE_SECONDS: Final[float] = 2.0
    # How close to its narration an attraction clip must end: closer than a
    # frame or so is left alone, anything more is trimmed or filled.
    _EXACT_FIT_SLACK_SECONDS: Final[float] = 0.05

    # Caps how long a single generated clip is actually asked to run for
    # (the `duration_sec` passed to _generate_single_clip), regardless of
    # narration length. ComfyUI/Wan2.2 already self-limits to roughly this
    # range via tuning.COMFYUI_MAX_FRAMES, but the local pan/zoom fallback
    # (local_pan_generator.py) has no such cap of its own — it renders
    # exactly `duration_sec` worth of frames, so an 18s narration on one
    # image used to generate an 18s clip outright (slow, and no longer
    # trimmed back down now that duration-fitting is disabled — see
    # _DURATION_FIT_ENABLED). Applied uniformly to both generators so
    # neither one is a surprise outlier.
    _MAX_GENERATED_CLIP_SECONDS: Final[float] = 5.0
    # ComfyUI's own ceiling once sequential extension is on: up to
    # tuning.COMFYUI_EXTEND_MAX_SEGMENTS chained segments (see
    # comfyui_i2v_client._resolve_segments) - or no ceiling at all when that's
    # None (chains to the whole narration; the user's choice). The 5s cap
    # above then applies only to the local pan/zoom fallback it was written
    # for.
    # Shots/parallax fill any length themselves (parallax is cheap, on the CPU).
    _MAX_EXTENDED_CLIP_SECONDS: Final[float] = (
        math.inf if tuning.ATTRACTION_GENERATOR in ("shots", "parallax")
        or tuning.COMFYUI_EXTEND_MAX_SEGMENTS is None
        else max(
            _MAX_GENERATED_CLIP_SECONDS,
            tuning.COMFYUI_EXTEND_MAX_SEGMENTS * tuning.COMFYUI_MAX_FRAMES / tuning.COMFYUI_GEN_FPS + 0.5,
        )
    )

    # No cap on how long _resolve_duration_fit will freeze-hold a clip's
    # last frame to cover an undershoot — the attraction clip must stay on
    # screen for the full narration rather than cutting away mid-sentence,
    # even when that means a long static hold (ComfyUI tops out around
    # ~5s, so narration routinely outlasts the generated motion by a lot).
    _MAX_HOLD_SECONDS: Final[float] = math.inf

    # Multi-image waypoints (2+ popup images -> 2+ generated clips) are no
    # longer auto-combined here — combining is deferred until the frontend
    # explicitly approves it (via finalize_pending_video), so a user gets a
    # chance to review the individual clips first. Raw clip paths + the
    # info needed to finish the job are parked here as a small manifest.
    _PENDING_SUBDIR: Final[str] = "pending_attraction"

    def _pending_manifest_path(self, output_filename: str) -> Path:
        pending_dir = self.output_dir / self._PENDING_SUBDIR
        pending_dir.mkdir(parents=True, exist_ok=True)
        return pending_dir / f"{Path(output_filename).stem}.json"

    # Which photo clips (by _clip_key) a deliverable was built from, so an
    # added/changed photo or preset rebuilds it. Older records hold "pans".
    _INPUTS_SUBDIR: Final[str] = "_inputs"

    def _inputs_path(self, output_filename: str) -> Path:
        return self.output_dir / self._INPUTS_SUBDIR / f"{Path(output_filename).stem}.json"

    def _read_inputs(self, output_filename: str) -> dict:
        try:
            with open(self._inputs_path(output_filename), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_inputs(
        self, output_filename: str, keys: List[str], pans: List[str],
        requested: Optional[dict] = None,
    ) -> None:
        """`requested`: seconds each photo clip (by key) was generated for."""
        path = self._inputs_path(output_filename)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"keys": keys, "pans": pans, "requested": requested or {}}, f)
        except OSError as exc:
            logger.warning("Could not record clip inputs for %s: %s", output_filename, exc)

    @staticmethod
    def _clip_key(image_path: str, pan: str) -> str:
        """Identifies one photo's raw clip by the photo's content and preset."""
        digest = hashlib.sha1()
        with open(image_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        digest.update(b"|" + pan.encode("utf-8"))
        # Switching generator rebuilds the kept clips.
        if pan in tuning.ATTRACTION_JUMP_CUT_PRESETS and tuning.ATTRACTION_ZOOM_STYLE == "dolly":
            digest.update(
                f"|dolly|{tuning.PARALLAX_ZOOM}|{tuning.PARALLAX_ARC}|{tuning.PARALLAX_FAR_WEIGHT}"
                f"|{tuning.PARALLAX_LAYERS}".encode("utf-8")
            )
        elif pan in tuning.ATTRACTION_JUMP_CUT_PRESETS:
            digest.update(
                f"|jumpcut|{tuning.ATTRACTION_JUMP_CUT_TIGHT}|{tuning.ATTRACTION_JUMP_CUT_AT}"
                f"|{tuning.ATTRACTION_AI_SURROUNDINGS}|{tuning.ATTRACTION_JUMP_CUT_AI_STRENGTH}".encode("utf-8")
            )
        elif pan in tuning.ATTRACTION_LTX_PRESETS:
            digest.update(f"|ltxv13b-crops|{tuning.ATTRACTION_SECOND_SHOT}".encode("utf-8"))
            digest.update(f"|{tuning.LTXV_PROMPTS.get(pan, '')}".encode("utf-8"))
            if pan in tuning.LTXV_DEPTH_KEYFRAMES:
                digest.update(
                    f"|depthkf|{tuning.LTXV_DEPTH_TRUCK}|{tuning.LTXV_DEPTH_PAN}|{tuning.LTXV_DEPTH_DOLLY}"
                    f"|{tuning.PARALLAX_FAR_WEIGHT}|{tuning.LTXV_DEPTH_MID_GUIDES}|{tuning.LTXV_MID_GUIDE_STRENGTH}".encode("utf-8")
                )
            digest.update(
                f"|{tuning.ATTRACTION_SECOND_SHOT_STYLE}|{','.join(tuning.ATTRACTION_SECOND_SHOT_MOVES)}"
                f"|{tuning.ATTRACTION_SECOND_SHOT_MIN_SOURCE_PX}|{tuning.LTXV_FREE_MOVE_FALLBACK}"
                f"|{tuning.LTXV_SMALL_PHOTO_WALK_FALLBACK}|{tuning.ATTRACTION_AI_SURROUNDINGS}".encode("utf-8")
            )
            if pan == "walkin":
                digest.update(
                    f"|{','.join(tuning.LTXV_FREE_MOVES)}|{tuning.WALKAI_STYLE}|{tuning.PARALLAX_WALK_DOLLY}"
                    f"|{tuning.PARALLAX_WALK_STEPS_PER_SEC}|{tuning.PARALLAX_WALK_BOB}|{tuning.PARALLAX_WALK_SWAY}"
                    f"|{tuning.PARALLAX_WALK_ROLL_DEG}|{tuning.LTXV_WALK_TO_SIGN}|{tuning.LTXV_WALK_SLOWDOWN}|{tuning.LTXV_WALK_ANCHOR_DOLLY}|{tuning.LTXV_WALK_ANCHOR_STRENGTH}"
                    f"|{tuning.LTXV_WALK_QC_MIN_SHARE}|{tuning.LTXV_WALK_ATTEMPTS}|walkqc1".encode("utf-8")
                )
        elif tuning.ATTRACTION_GENERATOR != "chain":
            digest.update(b"|" + tuning.ATTRACTION_GENERATOR.encode("utf-8"))
        return digest.hexdigest()[:12]

    # [NOTE] [IO] Called at the start of a fresh generate for a waypoint (the
    # user re-running it). Removes anything a previous run left behind for
    # the same output_filename — the finalized deliverable itself, and any
    # pending manifest + its now-superseded raw clips — so regenerating
    # doesn't silently leak old files that nothing else will ever clean up.
    def _clear_stale_outputs(self, output_filename: str) -> None:
        final_path = self.output_dir / output_filename
        if final_path.exists():
            try:
                final_path.unlink()
                logger.info(
                    "Removed previous deliverable before regenerating: %s", final_path
                )
            except OSError as exc:
                logger.warning("Could not remove old deliverable %s: %s", final_path, exc)

        manifest_path = self._pending_manifest_path(output_filename)
        if not manifest_path.exists():
            return

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                old_manifest = json.load(f)
        except (OSError, json.JSONDecodeError):
            old_manifest = {}

        for clip in old_manifest.get("clip_paths", []):
            if clip and os.path.exists(clip):
                try:
                    os.remove(clip)
                except OSError:
                    pass

        try:
            manifest_path.unlink()
        except OSError:
            pass
        logger.info(
            "Cleared stale pending manifest/clips for %s before regenerating.",
            output_filename,
        )

    # [NOTE] [Animation] Generates a single video clip from an image and prompt.
    #
    # Default path: the bundled ComfyUI server running Wan2.2-TI2V-5B-Turbo
    # (GGUF, Q6_K quant) — see comfyui_i2v_client.py. Earlier LTX-2 attempts
    # at the step counts/quantization an 8GB card forces were unreliable
    # (near-static output unless heavily prompted, prone to "melting" over
    # longer clips); Wan2.2's turbo checkpoint at 4 steps doesn't have that
    # problem. If the ComfyUI server can't be reached or a generation fails
    # for any reason, falls back to the local AI-outpaint + deterministic
    # pan/zoom generator (local_pan_generator.py) so a waypoint never
    # hard-fails just because the local GPU service had a bad run. See
    # services/model/ for the exploration that led to the local fallback.
    @staticmethod
    def _still_clip(image_path: str, output_path: str, duration_sec: float) -> Optional[str]:
        """The photo as a still clip, cropped to fill the attraction frame
        (same size/fps as a Wan clip). None if ffmpeg fails."""
        import subprocess

        from services.tts.ttsengine import FFmpegManager

        OUT_W, OUT_H = tuning.COMFYUI_WIDTH, tuning.COMFYUI_HEIGHT
        cmd = [
            FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_log_args(),
            "-loop", "1", "-i", image_path, "-t", f"{max(1.0, duration_sec):.3f}",
            "-vf", (
                f"scale={OUT_W}:{OUT_H}:force_original_aspect_ratio=increase,"
                f"crop={OUT_W}:{OUT_H},fps={tuning.COMFYUI_FPS},format=yuv420p"
            ),
            "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast",
            output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        if result.returncode != 0:
            logger.error("Still clip failed for %s: %s", image_path, result.stderr.strip())
            return None
        logger.info("Still clip (camera preset 'none') for %s", image_path)
        return output_path

    def _generate_single_clip(
        self,
        local_image_path: str,
        prompt_text: str,
        duration_sec: float = 6.0,
        save_path: Optional[str] = None,
        place: Optional[str] = None,
    ) -> Optional[str]:
        """Generates a clip via ComfyUI (Wan2.2 I2V), falling back to the
        local pan/zoom generator on failure. Returns the raw clip path.

        `save_path` lets the caller give this clip a deterministic name
        (rather than the old random-uuid one) so a checkpointed rerun can
        recognize and reuse it later — see the per-image loop in
        process_attraction_video."""
        save_path = Path(save_path) if save_path else self.output_dir / f"raw_{uuid.uuid4().hex[:6]}.mp4"

        from services.vdoprocessing.camera_pan import STILL_PRESET, normalize_camera_pan

        # The editor's "None" preset: the photo itself, held still (the
        # duration fit then holds it until the narration ends) - no ComfyUI.
        if normalize_camera_pan(prompt_text) == STILL_PRESET:
            return self._still_clip(local_image_path, str(save_path), duration_sec)

        if normalize_camera_pan(prompt_text) in tuning.ATTRACTION_JUMP_CUT_PRESETS:
            from services.vdoprocessing.jump_cut import generate_jump_cut, upscaled_photo

            photo = upscaled_photo(local_image_path, getattr(self.config, "config_path", None))
            if tuning.ATTRACTION_ZOOM_STYLE == "dolly":
                return self._parallax_clip(photo, str(save_path), duration_sec, prompt_text)
            return generate_jump_cut(photo, str(save_path), duration_sec, normalize_camera_pan(prompt_text))

        if normalize_camera_pan(prompt_text) in tuning.ATTRACTION_LTX_PRESETS:
            from services.vdoprocessing.ltx_keyframed import generate_ltx_move

            try:
                return generate_ltx_move(local_image_path, str(save_path), prompt_text, duration_sec, place)
            except Exception as exc:
                logger.warning(
                    "LTXV clip failed for %s (%s: %s) - 3D photo instead.",
                    local_image_path, type(exc).__name__, exc, exc_info=True,
                )
                return self._parallax_clip(local_image_path, str(save_path), duration_sec, prompt_text)

        if tuning.ATTRACTION_GENERATOR in ("shots", "parallax"):
            if tuning.ATTRACTION_GENERATOR == "shots":
                from services.vdoprocessing.shot_builder import build_shots

                try:
                    return build_shots(local_image_path, str(save_path), duration_sec, prompt_text)
                except Exception as exc:
                    logger.warning(
                        "Shot building failed for %s (%s: %s) - parallax only.",
                        local_image_path, type(exc).__name__, exc,
                    )
            return self._parallax_clip(local_image_path, str(save_path), duration_sec, prompt_text)

        from services.gpu_cooldown import wait_for_gpu_cooldown
        from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

        # Wan runs the GPU flat out; a hot GPU gets a short breather first.
        wait_for_gpu_cooldown(f"Wan clip for {Path(local_image_path).name}")
        try:
            ComfyUII2VClient().generate_clip(
                image_path=local_image_path,
                output_path=str(save_path),
                duration_sec=duration_sec,
                camera_pan_hint=prompt_text,
            )
        except Exception as exc:
            logger.warning(
                "ComfyUI clip generation failed for %s (%s: %s) — falling back "
                "to local pan/zoom generator.",
                local_image_path, type(exc).__name__, exc,
            )
        else:
            # Wan grades its output (contrast, saturation, brightness jumps
            # between segments); put the photo's own colours back.
            from services.vdoprocessing.color_match import match_clip_to_photo

            match_clip_to_photo(str(save_path), local_image_path)
            return str(save_path)

        return self._parallax_clip(local_image_path, str(save_path), duration_sec, prompt_text)

    @staticmethod
    def _parallax_clip(image_path: str, save_path: str, duration_sec: float, preset) -> Optional[str]:
        """The depth-parallax move over the photo (CPU, nothing generated); None on failure."""
        try:
            from services.vdoprocessing.parallax_generator import generate_parallax_clip

            return generate_parallax_clip(image_path, save_path, duration_sec, preset)
        except Exception as exc:
            logger.error("Parallax clip failed for %s (%s: %s)", image_path, type(exc).__name__, exc)
            return None

    # [NOTE] [Editor] Decides whether a generated clip needs trimming (runs
    # too long past the narration) or holding (runs too short) to land
    # within `overshoot_tolerance` of target_audio_duration. Returns
    # (trim_to, hold_to) — at most one is non-None; both None means the
    # clip is already close enough to use as-is.
    #
    # Undershoot is handled by freezing the last frame for the gap (hold_to)
    # rather than slow-motion PTS-stretching the whole clip — ComfyUI/Wan is
    # hard-capped at tuning.COMFYUI_MAX_FRAMES (~5s at COMFYUI_FPS), while
    # real narration routinely runs 15-30s, so a naive stretch here would
    # play the clip at roughly a fifth speed. That doesn't just look slow —
    # a generated clip's motion is already only approximately stable (fast/
    # turbo low-step diffusion), and stretching it 3-6x turns any small
    # per-frame drift into obvious, ugly wobble. Holding the last frame
    # keeps the actual generated motion at its native, correct speed and
    # only pads with a static frame, which is unnoticeable by comparison.
    # Narration-based fitting is enabled: a clip that overshoots is trimmed
    # to target_audio_duration, and a clip that undershoots is held on its
    # last frame for the full gap (no cap — see _MAX_HOLD_SECONDS above) so
    # the attraction clip never cuts away before its narration finishes.
    _DURATION_FIT_ENABLED: Final[bool] = True

    def _resolve_duration_fit(
        self,
        video_path: str,
        target_audio_duration: float,
        overshoot_tolerance: float,
        generation_cap: bool = True,
    ) -> Tuple[Optional[float], Optional[float]]:
        from services.tts.ttsengine import FFmpegManager

        current_duration = FFmpegManager.get_media_duration(video_path)
        if current_duration <= 0:
            return None, None

        # Flat hard cap, independent of narration length — trim only, no
        # hold/stretch, regardless of _DURATION_FIT_ENABLED below. Only for a
        # clip straight out of a generator: one already extended by the slow
        # move or combined from several photos is meant to be long.
        if generation_cap and current_duration > self._MAX_EXTENDED_CLIP_SECONDS:
            return self._MAX_EXTENDED_CLIP_SECONDS, None

        if not self._DURATION_FIT_ENABLED:
            return None, None
        if target_audio_duration <= 0:
            return None, None

        # Exact fit: an attraction clip lasts exactly as long as its
        # narration. A gap inside `overshoot_tolerance` used to be left for
        # the export to freeze (a visible freeze at the end), so any gap or
        # overrun past _EXACT_FIT_SLACK_SECONDS is now fitted here instead.
        overshoot = current_duration - target_audio_duration
        if overshoot > self._EXACT_FIT_SLACK_SECONDS:
            return target_audio_duration, None
        if overshoot < -self._EXACT_FIT_SLACK_SECONDS:
            capped_hold_to = min(target_audio_duration, current_duration + self._MAX_HOLD_SECONDS)
            if capped_hold_to < target_audio_duration - 0.05:
                logger.warning(
                    "Clip is %.1fs short of its %.1fs narration — holding only "
                    "%.1fs (capped at +%.1fs) instead of freezing for the full "
                    "gap. %.1fs of narration will play with no matching visual; "
                    "add another popup image to this waypoint to cover it.",
                    target_audio_duration - current_duration, target_audio_duration,
                    capped_hold_to, self._MAX_HOLD_SECONDS,
                    target_audio_duration - capped_hold_to,
                )
            return None, capped_hold_to
        return None, None

    # [NOTE] [Editor] Shared tail end of clip processing: fit duration, place at the
    # project's output path, and upscale. Used by both the single-image path
    # in process_attraction_video and finalize_pending_video's multi-image
    # path, so the two stay in sync instead of drifting apart.
    def _fit_and_finalize(
        self,
        video_path: str,
        target_audio_duration: float,
        output_filename: str,
        overshoot_tolerance: float,
        place_label: Optional[str] = None,
        camera_pan=None,
        generation_cap: bool = True,
    ) -> str:
        """Trims/stretches video_path to within tolerance of
        target_audio_duration, upscales it, and (if place_label is given)
        burns it into the top-left corner — all in a single ffmpeg pass via
        VideoExporter.finalize_clip, falling back to the old three-pass
        per-stage pipeline only if that fused pass itself fails outright
        (kept as a safety net; each stage there can fail independently
        without losing the whole clip). Narration audio is intentionally
        NOT muxed in here — see process_attraction_video's docstring for
        why."""
        from services.vdoprocessing.camera_pan import STILL_PRESET, normalize_camera_pan

        # A still photo ("none") is simply held to the narration length - the
        # raw-clip cap is for generated motion, and made a still stop at ~8s.
        if normalize_camera_pan(camera_pan) in (STILL_PRESET, *tuning.ATTRACTION_JUMP_CUT_PRESETS):
            generation_cap = False
        trim_to, hold_to = self._resolve_duration_fit(
            video_path, target_audio_duration, overshoot_tolerance, generation_cap
        )
        # A moving preset whose Wan clip falls short (the segment cap) keeps
        # moving via slow_move.py instead of freezing; see _fill_with_slow_move.
        from services.tts.ttsengine import FFmpegManager
        from services.vdoprocessing.slow_move import extend_with_slow_move, is_moving_preset

        moved_path = self.output_dir / f"moved_{Path(output_filename).stem}.mp4"
        if (
            hold_to is not None and target_audio_duration > 0 and is_moving_preset(camera_pan)
            and self._fill_with_slow_move(
                target_audio_duration - FFmpegManager.get_media_duration(video_path)
            )
        ):
            moved = extend_with_slow_move(
                video_path, target_audio_duration, camera_pan, str(moved_path),
            )
            if moved:
                video_path = moved
                trim_to, hold_to = self._resolve_duration_fit(
                    video_path, target_audio_duration, overshoot_tolerance, generation_cap=False
                )

        final_path = self.output_dir / output_filename
        if final_path.exists():
            final_path.unlink()

        # [NOTE] [Editor] Duration-fit + upscale + label burn used to be three
        # sequential ffmpeg re-encodes (trim/adjust, then a separate upscale
        # pass, then a separate label-burn pass) — three full decode/encode
        # passes over the same clip. finalize_clip fuses whichever of those
        # are actually needed into one filter graph and one encode.
        # The place name goes on the editor's text track instead of into the pixels.
        from services.vdoprocessing.place_label import record_place_label

        on_track = tuning.ATTRACTION_LABEL_ON_TEXT_TRACK
        burned_label = None if on_track else place_label
        try:
            try:
                VideoExporter.finalize_clip(
                    input_video_path=video_path,
                    output_video_path=str(final_path),
                    trim_to=trim_to,
                    hold_to=hold_to,
                    scale_to=(self._TARGET_WIDTH, self._TARGET_HEIGHT),
                    sharpen=tuning.ATTRACTION_UPSCALE_SHARPEN,
                    label_text=burned_label,
                )
                record_place_label(final_path, place_label, burned=not on_track)
                return str(final_path)
            except Exception as exc:
                logger.warning(
                    "Fused finalize (trim/scale/label in one pass) failed for %s "
                    "(%s: %s) — falling back to the slower per-stage pipeline.",
                    video_path, type(exc).__name__, exc,
                )

            result = self._fit_and_finalize_stagewise(
                video_path, trim_to, hold_to, final_path, burned_label
            )
            record_place_label(result, place_label, burned=not on_track)
            return result
        finally:
            moved_path.unlink(missing_ok=True)

    # [Core] Slow-path fallback for _fit_and_finalize: the original
    # three-separate-ffmpeg-passes implementation, kept so a fused-pass
    # failure (e.g. an unusual filter-graph edge case) degrades to something
    # slower rather than losing the clip — each stage here fails
    # independently (a label or upscale problem doesn't sink the clip).
    def _fit_and_finalize_stagewise(
        self,
        video_path: str,
        trim_to: Optional[float],
        hold_to: Optional[float],
        final_path: Path,
        place_label: Optional[str] = None,
    ) -> str:
        temp_fitted_video: Optional[str] = None
        if trim_to is not None:
            trimmed_name = f"temp_trimmed_{uuid.uuid4().hex[:8]}.mp4"
            fitted_video = self.editor.trim_video_duration(
                video_path=video_path,
                target_duration=trim_to,
                output_filename=trimmed_name,
            )
            temp_fitted_video = fitted_video
        elif hold_to is not None:
            held_name = f"temp_held_{uuid.uuid4().hex[:8]}.mp4"
            fitted_video = self.editor.hold_last_frame(
                video_path=video_path,
                target_duration=hold_to,
                output_filename=held_name,
            )
            temp_fitted_video = fitted_video
        else:
            fitted_video = video_path

        try:
            if Path(fitted_video).resolve() != final_path.resolve():
                if final_path.exists():
                    final_path.unlink()
                shutil.copy2(fitted_video, final_path)
        finally:
            # temp_trimmed_*/temp_scaled_* was copied from, not moved —
            # without this it's left behind on disk permanently every time
            # this fallback path runs.
            if temp_fitted_video and os.path.exists(temp_fitted_video):
                try:
                    os.remove(temp_fitted_video)
                except OSError:
                    pass
        final_output = str(final_path)

        try:
            upscale_tmp = str(
                Path(final_output).with_name(f"upscaled_{uuid.uuid4().hex[:6]}.mp4")
            )
            VideoExporter.upscale_video(
                input_video_path=final_output,
                output_video_path=upscale_tmp,
                target_width=self._TARGET_WIDTH,
                target_height=self._TARGET_HEIGHT,
            )
            os.replace(upscale_tmp, final_output)
        except Exception as exc:
            logger.warning(
                "Upscale failed for %s (%s) — keeping original resolution.",
                final_output,
                exc,
            )

        if place_label:
            try:
                labeled_tmp = str(
                    Path(final_output).with_name(f"labeled_{uuid.uuid4().hex[:6]}.mp4")
                )
                VideoExporter.burn_static_label(
                    input_video_path=final_output,
                    text=place_label,
                    output_video_path=labeled_tmp,
                )
                os.replace(labeled_tmp, final_output)
            except Exception as exc:
                logger.warning(
                    "Place-name label burn failed for %s (%s) — keeping clip unlabeled.",
                    final_output,
                    exc,
                )

        return final_output

    # [NOTE] [Animation] Combines previously-generated attraction clips into
    # one waypoint video, once the frontend has reviewed and approved them.
    def finalize_pending_video(
        self,
        clip_paths: List[str],
        target_audio_duration: float,
        output_filename: str,
        place_label: Optional[str] = None,
    ) -> Optional[str]:
        """
        Call this once the frontend confirms it's okay to combine a
        waypoint's clips (the ones process_attraction_video parked in a
        pending-manifest instead of auto-combining). Mirrors the tail end
        of process_attraction_video, starting from already-rendered clips
        instead of generating new ones. Narration audio is still not muxed
        in here — same deferral as process_attraction_video.
        """
        valid_clips = [c for c in clip_paths if c and os.path.exists(c)]
        if not valid_clips:
            logger.error("finalize_pending_video: no valid clip paths given.")
            return None

        temp_combined_video: Optional[str] = None
        if len(valid_clips) > 1:
            logger.info(
                f"Combining {len(valid_clips)} approved clips into a sequence..."
            )
            temp_combined_name = f"temp_concat_{uuid.uuid4().hex[:8]}.mp4"
            combined_video = self.editor.concatenate_videos(
                input_paths=valid_clips, output_filename=temp_combined_name
            )
            temp_combined_video = combined_video
            overshoot_tolerance = self._MULTI_IMAGE_OVERSHOOT_TOLERANCE_SECONDS
        else:
            combined_video = valid_clips[0]
            overshoot_tolerance = self._AUDIO_DURATION_TOLERANCE_SECONDS

        try:
            final_output = self._fit_and_finalize(
                combined_video, target_audio_duration, output_filename, overshoot_tolerance,
                place_label=place_label,
            )
        finally:
            # temp_concat_* was only ever an intermediate input to
            # _fit_and_finalize, never cleaned up afterward — leaked to disk
            # on every multi-clip finalize otherwise.
            if temp_combined_video and os.path.exists(temp_combined_video):
                try:
                    os.remove(temp_combined_video)
                except OSError:
                    pass

        for clip in valid_clips:
            if os.path.exists(clip) and clip != final_output:
                try:
                    os.remove(clip)
                except OSError:
                    pass

        manifest_path = self._pending_manifest_path(output_filename)
        if manifest_path.exists():
            try:
                manifest_path.unlink()
            except OSError:
                pass

        logger.info(f"Waypoint video deliverable complete (finalized): {final_output}")
        return final_output

    @staticmethod
    def _fill_with_slow_move(gap: float) -> bool:
        """Whether a moving clip `gap` seconds short of its narration gets
        slow_move's tail rather than a last-frame hold: only a real shortfall
        (over 1s), and only when the Wan chain may stop short (capped, or
        chain-to-full-length off)."""
        return gap > 1.0 and (
            not tuning.ATTRACTION_CHAIN_TO_FULL_LENGTH
            or tuning.COMFYUI_EXTEND_MAX_SEGMENTS is not None
        )

    def _fit_clip_to_share(
        self, clip_path: str, share: float, camera_pan, out_path: Path,
    ) -> str:
        """One photo's clip made exactly `share` seconds long: trimmed if
        longer; if shorter, continued with the slow move for a moving preset,
        or held still for "none". Returns the path to use (clip_path itself
        when it already fits)."""
        from services.tts.ttsengine import FFmpegManager
        from services.vdoprocessing.slow_move import extend_with_slow_move, is_moving_preset

        duration = FFmpegManager.get_media_duration(clip_path)
        if abs(duration - share) <= 0.05:
            return clip_path
        if duration > share:
            return self.editor.trim_video_duration(clip_path, share, str(out_path))
        if is_moving_preset(camera_pan) and self._fill_with_slow_move(share - duration):
            moved = extend_with_slow_move(clip_path, share, camera_pan, str(out_path))
            if moved:
                return moved
        return self.editor.hold_last_frame(clip_path, share, str(out_path))

    @staticmethod
    def _concat_reencoded(paths: List[str], output_path: str) -> None:
        """Joins clips in order, re-encoded at one size/fps: the pieces come
        from different encoders (Wan, still photo, slow-move tail), which a
        stream-copy join can glitch on. At the final size, so 1920x1080
        shot/parallax clips aren't shrunk and blown back up."""
        from services.vdoprocessing.shot_builder import concat_clips

        concat_clips(
            paths, output_path,
            AttractionVideoGenerator._TARGET_WIDTH, AttractionVideoGenerator._TARGET_HEIGHT,
            tuning.COMFYUI_FPS,
        )

    def _combine_clips(
        self,
        clips: List[str],
        presets: List,
        target_audio_duration: float,
        output_filename: str,
        place_label: Optional[str],
    ) -> Optional[str]:
        """A multi-photo waypoint's clips as one deliverable: each fitted to
        an equal share of the narration (_fit_clip_to_share), joined in
        order, then finalized like a single clip."""
        stem = Path(output_filename).stem
        share = target_audio_duration / len(clips) if target_audio_duration > 0 else None
        temps: List[str] = []
        try:
            fitted = []
            for i, (clip, preset) in enumerate(zip(clips, presets)):
                if share is None:
                    fitted.append(clip)
                    continue
                path = self._fit_clip_to_share(
                    clip, share, preset, self.output_dir / f"share_{stem}_{i:02d}.mp4"
                )
                if path != clip:
                    temps.append(path)
                fitted.append(path)
            combined = str(self.output_dir / f"combined_{stem}.mp4")
            temps.append(combined)
            self._concat_reencoded(fitted, combined)
            logger.info(
                "Combined %d photo clips (%.1fs each) for %s.",
                len(clips), share or 0.0, output_filename,
            )
            final_output = self._fit_and_finalize(
                combined, target_audio_duration, output_filename,
                self._MULTI_IMAGE_OVERSHOOT_TOLERANCE_SECONDS, place_label=place_label,
                generation_cap=False,
            )
        except Exception as exc:
            logger.error("Combining clips for %s failed: %s", output_filename, exc)
            return None
        finally:
            for path in temps:
                Path(path).unlink(missing_ok=True)

        # Raw photo clips are kept: a later run reuses unchanged photos.
        self._pending_manifest_path(output_filename).unlink(missing_ok=True)
        logger.info(f"Waypoint video deliverable complete: {final_output}")
        return final_output

    # [NOTE] [Animation] Main processing function for attraction video generation
    def process_attraction_video(
        self,
        popup_image_entry: Union[str, List[str], None],
        prompt_text: Union[str, List[str]],
        target_audio_duration: float,
        audio_path: Optional[str] = None,
        output_filename: str = "waypoint_final.mp4",
        place_label: Optional[str] = None,
        force: bool = False,
    ) -> Optional[str]:
        """
        Main processor:
        1. Checks if popup_image is a list or single string.
        2. Generates clips for all images using paired prompts.
        3. Single image: fits duration, upscales, returns the finished
           (audio-less) clip. Multi-image: does NOT auto-combine — writes a
           pending manifest and returns None; call finalize_pending_video()
           once the frontend approves combining the clips.
        4. Narration audio is deliberately NOT muxed in — subtitles still
           get burned onto whatever's returned via the normal pipeline
           subtitle step, but audio muxing is a separate, later step so a
           human gets a chance to review the clip(s) first.

        Checkpointing (skipped entirely when `force` is True):
        - If the final deliverable already exists, returns it immediately.
        - If a pending manifest already exists and every clip it lists is
          still present, leaves it alone (still awaiting finalize) instead
          of regenerating.
        - The deliverable is rebuilt when its photos or presets change.
        - Each photo's raw clip is kept as raw_<output stem>_<_clip_key>.mp4
          (photo content + preset) and reused while it's long enough for its
          share — adding a photo only generates the new one; the others are
          trimmed to their new share.
        """
        if not popup_image_entry:
            logger.warning("No popup image provided for waypoint.")
            return None

        # --- Check list vs string for images ---
        if isinstance(popup_image_entry, list):
            image_list = [
                img for img in popup_image_entry if img and os.path.exists(img)
            ]
        elif isinstance(popup_image_entry, str) and os.path.exists(popup_image_entry):
            image_list = [popup_image_entry]
        else:
            logger.error(f"Invalid image entry: {popup_image_entry}")
            return None

        if not image_list:
            return None

        if isinstance(prompt_text, str):
            prompt_list = [prompt_text]
        elif isinstance(prompt_text, list):
            prompt_list = prompt_text
        else:
            prompt_list = [""]

        from services.vdoprocessing.camera_pan import normalize_camera_pan

        pans = [
            normalize_camera_pan(prompt_list[min(i, len(prompt_list) - 1)] if prompt_list else "")
            for i in range(len(image_list))
        ]
        keys = [self._clip_key(img, pan) for img, pan in zip(image_list, pans)]
        recorded = self._read_inputs(output_filename)
        if "keys" in recorded:
            inputs_changed = recorded["keys"] != keys
        elif "pans" in recorded:
            inputs_changed = recorded["pans"] != pans
        else:
            inputs_changed = False  # made before this check: keep it, adopt current inputs
        if inputs_changed:
            logger.info(
                "Photos or camera presets changed for %s — rebuilding it "
                "(unchanged photos reuse their clips).", output_filename,
            )

        final_path = self.output_dir / output_filename
        if not force and not inputs_changed and output_is_valid(final_path):
            if "keys" not in recorded:
                self._write_inputs(output_filename, keys, pans)
            logger.info(
                "Waypoint deliverable already exists — skipping generation: %s",
                final_path,
            )
            return str(final_path)

        # Rebuilding: drop the old deliverable/pending manifest. Raw photo
        # clips stay for reuse, unless force=True.
        self._clear_stale_outputs(output_filename)
        stem = Path(output_filename).stem
        if force:
            for stale_raw in self.output_dir.glob(f"raw_{stem}_*.mp4"):
                try:
                    stale_raw.unlink()
                    Path(str(stale_raw) + ".signlock").unlink(missing_ok=True)
                except OSError:
                    pass
        else:
            self._migrate_index_named_raws(stem, keys, pans, recorded.get("pans"))

        logger.info(f"Processing waypoint with {len(image_list)} image(s)...")

        # 1. Generate video clips for each image
        # Split the target narration duration evenly across multiple images
        # in one waypoint (so the concatenated result lands near the target
        # instead of badly overshooting); fall back to a reasonable default
        # when there's no narration yet to size against.
        # No narration: one normal Wan generation per photo (a single
        # COMFYUI_MAX_FRAMES segment, ~3.7s), no extension.
        _DEFAULT_CLIP_SECONDS = tuning.COMFYUI_MAX_FRAMES / tuning.COMFYUI_GEN_FPS
        per_clip_duration = (
            (target_audio_duration / len(image_list))
            if target_audio_duration > 0
            else _DEFAULT_CLIP_SECONDS
        )
        per_clip_duration = min(per_clip_duration, self._MAX_EXTENDED_CLIP_SECONDS)

        generated_clips = []
        clip_presets = []
        built_keys = []
        requested_by_key = dict(recorded.get("requested") or {})
        for idx, img_path in enumerate(image_list):
            # Match image index to prompt index (fallback to the last prompt if we run out)
            current_prompt = (
                prompt_list[idx]
                if idx < len(prompt_list)
                else (prompt_list[-1] if prompt_list else "")
            )

            raw_clip_path = self.output_dir / f"raw_{stem}_{keys[idx]}.mp4"
            if not force and self._raw_clip_covers(
                raw_clip_path, requested_by_key.get(keys[idx]), per_clip_duration
            ):
                logger.info(
                    "   -> Image %d/%d already rendered — reusing %s",
                    idx + 1, len(image_list), raw_clip_path,
                )
                self._lock_signs(str(raw_clip_path), img_path, pans[idx])
                generated_clips.append(str(raw_clip_path))
                clip_presets.append(current_prompt)
                built_keys.append(keys[idx])
                continue

            raw_clip_path.unlink(missing_ok=True)
            Path(str(raw_clip_path) + ".signlock").unlink(missing_ok=True)
            logger.info(
                f"   -> Rendering image {idx + 1}/{len(image_list)}: {img_path} with prompt: '{current_prompt}'"
            )
            clip = self._generate_single_clip(
                img_path, current_prompt, per_clip_duration, save_path=str(raw_clip_path), place=place_label,
            )
            if clip:
                self._lock_signs(clip, img_path, pans[idx])
                generated_clips.append(clip)
                clip_presets.append(current_prompt)
                built_keys.append(keys[idx])
                requested_by_key[keys[idx]] = per_clip_duration

        if not generated_clips:
            logger.error("Failed to generate any video clips.")
            return None

        # 2. Multiple images -> combined here, in order, each photo taking an
        # equal share of the narration, so the whole clip lasts as long as
        # the narration. (It used to be parked for an approval step nothing
        # in the app ever triggers, so these waypoints had no attraction
        # video at all.)
        if len(generated_clips) > 1:
            final_output = self._combine_clips(
                generated_clips, clip_presets, target_audio_duration, output_filename, place_label,
            )
        else:
            # 3. Single image: fit duration, place at output_filename, upscale.
            # Narration audio is NOT muxed in here — see docstring.
            final_output = self._fit_and_finalize(
                generated_clips[0],
                target_audio_duration,
                output_filename,
                overshoot_tolerance=self._AUDIO_DURATION_TOLERANCE_SECONDS,
                place_label=place_label,
                camera_pan=clip_presets[0],
            )
            logger.info(f"Waypoint video deliverable complete: {final_output}")

        if final_output:
            # Only the photos that made it in: a failed photo is retried next run.
            self._write_inputs(
                output_filename, built_keys, pans,
                {k: requested_by_key[k] for k in built_keys if k in requested_by_key},
            )
            self._remove_orphan_raws(stem, keys)
        return final_output

    @staticmethod
    def _raw_clip_covers(raw_path: Path, requested: Optional[float], needed: float) -> bool:
        """A kept photo clip is reusable if it was generated for at least its
        current share (made for a shorter one, Wan would stop moving early).
        Unknown request length (older clips): reuse."""
        if not output_is_valid(raw_path):
            return False
        if requested is not None and requested < needed - 0.1:
            logger.info(
                "   -> %s was made for %.1fs, its share is now %.1fs — regenerating.",
                raw_path.name, requested, needed,
            )
            return False
        return True

    def _migrate_index_named_raws(
        self, stem: str, keys: List[str], pans: List[str], recorded_pans: Optional[List[str]],
    ) -> None:
        """Renames raw_<stem>_<idx>.mp4 clips from before content keys, when
        the recorded presets show they were made for the same photos."""
        if not recorded_pans or len(recorded_pans) != len(pans):
            return
        for idx, key in enumerate(keys):
            old = self.output_dir / f"raw_{stem}_{idx:02d}.mp4"
            new = self.output_dir / f"raw_{stem}_{key}.mp4"
            if not old.exists() or new.exists() or recorded_pans[idx] != pans[idx]:
                continue
            try:
                old.replace(new)
                leftover = old.with_suffix(".colormatch.mp4")
                if leftover.exists():
                    leftover.replace(new.with_suffix(".colormatch.mp4"))
                logger.info("Kept earlier clip %s as %s.", old.name, new.name)
            except OSError as exc:
                logger.warning("Could not rename %s: %s", old.name, exc)

    @staticmethod
    def _lock_signs(clip_path: str, photo_path: str, pan: str) -> None:
        """Pastes the photo's real signs over the generated ones, once per raw
        clip (a .signlock marker beside it; reused clips get it on their next
        build). Still clips are the photo itself and are skipped."""
        from services.vdoprocessing.camera_pan import STILL_PRESET

        marker = Path(clip_path + ".signlock")
        if (not tuning.SIGN_LOCK or pan in (STILL_PRESET, *tuning.ATTRACTION_JUMP_CUT_PRESETS)
                or marker.exists()):
            return
        from services.vdoprocessing.sign_lock import lock_signs

        lock_signs(clip_path, photo_path)
        try:
            marker.touch()
        except OSError:
            pass

    def _remove_orphan_raws(self, stem: str, keys: List[str]) -> None:
        """Deletes kept photo clips no current photo/preset uses."""
        import re

        wanted = set(keys)
        pattern = re.compile(re.escape(f"raw_{stem}_") + r"([0-9a-f]{12}|\d{2})(\.colormatch)?")
        for raw in self.output_dir.glob("raw_*.mp4"):
            m = pattern.fullmatch(raw.stem)
            if m and m.group(1) not in wanted:
                raw.unlink(missing_ok=True)
                Path(str(raw) + ".signlock").unlink(missing_ok=True)