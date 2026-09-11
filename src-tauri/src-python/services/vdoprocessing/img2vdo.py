"""
Image-to-Video Service for Attractions
----------------------------------------------------------------------------
Handles image-to-video generation (ComfyUI/Wan2.2, falling back to local
AI-outpaint + pan on failure), multi-image list detection, concatenation
via VideoEditor, and audio synchronization.
----------------------------------------------------------------------------
"""

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

    # Caps how long _resolve_duration_fit will freeze-hold a clip's last
    # frame to cover an undershoot. A short narration only a little longer
    # than the clip is fine to pad; a clip that's, say, 20s short of its
    # narration (routine here, since ComfyUI tops out around ~5s) would
    # otherwise freeze on a static frame for 20 straight seconds — just as
    # broken-looking as the slow-motion stretch this replaced, just in a
    # different way. Past this cap, the clip is deliberately left short
    # rather than forced to fit; see the warning _resolve_duration_fit logs
    # when it happens — the fix is for the waypoint to gain another popup
    # image (covering the rest of the narration with its own clip), not a
    # bigger freeze.
    _MAX_HOLD_SECONDS: Final[float] = 3.0

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

    # [NOTE] [IO] Called at the start of a fresh generate for a waypoint (the
    # user re-running it). Removes anything a previous run left behind for
    # the same output_filename — the finalized deliverable itself, and any
    # pending manifest + its now-superseded raw clips — so regenerating
    # doesn't silently leak old files that nothing else will ever clean up.
    def _clear_stale_outputs(self, output_filename: str) -> None:
        final_path = self.editor._resolve_output_path(output_filename, "video")
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
    def _generate_single_clip(
        self,
        local_image_path: str,
        prompt_text: str,
        duration_sec: float = 6.0,
        save_path: Optional[str] = None,
    ) -> Optional[str]:
        """Generates a clip via ComfyUI (Wan2.2 I2V), falling back to the
        local pan/zoom generator on failure. Returns the raw clip path.

        `save_path` lets the caller give this clip a deterministic name
        (rather than the old random-uuid one) so a checkpointed rerun can
        recognize and reuse it later — see the per-image loop in
        process_attraction_video."""
        save_path = Path(save_path) if save_path else self.output_dir / f"raw_{uuid.uuid4().hex[:6]}.mp4"

        from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

        try:
            ComfyUII2VClient().generate_clip(
                image_path=local_image_path,
                output_path=str(save_path),
                duration_sec=duration_sec,
                camera_pan_hint=prompt_text,
            )
            return str(save_path)
        except Exception as exc:
            logger.warning(
                "ComfyUI clip generation failed for %s (%s: %s) — falling back "
                "to local pan/zoom generator.",
                local_image_path, type(exc).__name__, exc,
            )

        try:
            # [FIXME] [Animation] Import moved inside this try — it previously sat
            # above it, so a missing torch/diffusers/transformers install (the local
            # fallback's own dependencies, not bundled by default) raised
            # ModuleNotFoundError uncaught, crashing the whole waypoint instead of
            # the graceful None this function's docstring promises.
            from services.vdoprocessing.local_pan_generator import generate_local_clip

            generate_local_clip(
                image_path=local_image_path,
                output_path=str(save_path),
                duration_sec=duration_sec,
                camera_pan_hint=prompt_text,
            )
            return str(save_path)
        except ModuleNotFoundError as exc:
            logger.error(
                "Local pan/zoom fallback unavailable for %s — its dependencies "
                "(torch/diffusers/transformers) aren't installed: %s",
                local_image_path, exc,
            )
            return None
        except Exception as exc:
            logger.error("Local clip generation failed for %s: %s", local_image_path, exc)
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
    # Narration-based fitting (trim to match narration if too long, freeze-
    # hold if too short) is disabled — clips are no longer sized against
    # target_audio_duration at all. Instead, _resolve_duration_fit only ever
    # hard-trims a clip down to _MAX_GENERATED_CLIP_SECONDS if it somehow
    # runs longer than that (generation should already cap it there via
    # per_clip_duration, but this is the backstop) — never holds/stretches,
    # and never extends a short clip to "catch up" to the narration.
    _DURATION_FIT_ENABLED: Final[bool] = False

    def _resolve_duration_fit(
        self,
        video_path: str,
        target_audio_duration: float,
        overshoot_tolerance: float,
    ) -> Tuple[Optional[float], Optional[float]]:
        from services.tts.ttsengine import FFmpegManager

        current_duration = FFmpegManager.get_media_duration(video_path)
        if current_duration <= 0:
            return None, None

        # Flat hard cap, independent of narration length — trim only, no
        # hold/stretch, regardless of _DURATION_FIT_ENABLED below.
        if current_duration > self._MAX_GENERATED_CLIP_SECONDS:
            return self._MAX_GENERATED_CLIP_SECONDS, None

        if not self._DURATION_FIT_ENABLED:
            return None, None
        if target_audio_duration <= 0:
            return None, None

        overshoot = current_duration - target_audio_duration
        if overshoot > overshoot_tolerance:
            return target_audio_duration, None
        if overshoot < -overshoot_tolerance:
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
        trim_to, hold_to = self._resolve_duration_fit(
            video_path, target_audio_duration, overshoot_tolerance
        )

        final_path = self.editor._resolve_output_path(output_filename, "video")
        if final_path.exists():
            final_path.unlink()

        # [NOTE] [Editor] Duration-fit + upscale + label burn used to be three
        # sequential ffmpeg re-encodes (trim/adjust, then a separate upscale
        # pass, then a separate label-burn pass) — three full decode/encode
        # passes over the same clip. finalize_clip fuses whichever of those
        # are actually needed into one filter graph and one encode.
        try:
            VideoExporter.finalize_clip(
                input_video_path=video_path,
                output_video_path=str(final_path),
                trim_to=trim_to,
                hold_to=hold_to,
                scale_to=(self._TARGET_WIDTH, self._TARGET_HEIGHT),
                sharpen=tuning.ATTRACTION_UPSCALE_SHARPEN,
                label_text=place_label,
            )
            return str(final_path)
        except Exception as exc:
            logger.warning(
                "Fused finalize (trim/scale/label in one pass) failed for %s "
                "(%s: %s) — falling back to the slower per-stage pipeline.",
                video_path, type(exc).__name__, exc,
            )

        return self._fit_and_finalize_stagewise(
            video_path, trim_to, hold_to, final_path, place_label
        )

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
        - Otherwise, each per-image raw clip is generated to a deterministic
          filename (raw_<output stem>_<index>.mp4) and reused if it already
          exists — so a run interrupted partway through a multi-image
          waypoint only regenerates the images it hadn't finished yet.
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

        final_path = self.editor._resolve_output_path(output_filename, "video")
        if not force and output_is_valid(final_path):
            logger.info(
                "Waypoint deliverable already exists — skipping generation: %s",
                final_path,
            )
            return str(final_path)

        manifest_path = self._pending_manifest_path(output_filename)
        if not force and manifest_path.exists():
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    existing_manifest = json.load(f)
            except (OSError, json.JSONDecodeError):
                existing_manifest = {}
            existing_clips = existing_manifest.get("clip_paths", [])
            if existing_clips and all(output_is_valid(c) for c in existing_clips):
                logger.info(
                    "Waypoint already has %d clip(s) pending approval — "
                    "leaving as-is (call attraction-finalize once ready).",
                    len(existing_clips),
                )
                return None

        # Regenerating this waypoint — clear out whatever a previous run
        # left behind (old deliverable, old pending manifest + its clips)
        # before doing any fresh work. Deterministic per-image raw clips
        # (raw_<stem>_<idx>.mp4) are deliberately left alone here so the
        # per-image loop below can still reuse ones from an interrupted
        # run — force=True sweeps them up separately.
        self._clear_stale_outputs(output_filename)
        if force:
            stem = Path(output_filename).stem
            for stale_raw in self.output_dir.glob(f"raw_{stem}_*.mp4"):
                try:
                    stale_raw.unlink()
                except OSError:
                    pass

        # --- Check list vs string for prompts ---
        if isinstance(prompt_text, str):
            prompt_list = [prompt_text]
        elif isinstance(prompt_text, list):
            prompt_list = prompt_text
        else:
            prompt_list = [""]

        logger.info(f"Processing waypoint with {len(image_list)} image(s)...")

        # 1. Generate video clips for each image
        # Split the target narration duration evenly across multiple images
        # in one waypoint (so the concatenated result lands near the target
        # instead of badly overshooting); fall back to a reasonable default
        # when there's no narration yet to size against.
        _DEFAULT_CLIP_SECONDS = 6.0
        per_clip_duration = (
            (target_audio_duration / len(image_list))
            if target_audio_duration > 0
            else _DEFAULT_CLIP_SECONDS
        )
        per_clip_duration = min(per_clip_duration, self._MAX_GENERATED_CLIP_SECONDS)

        stem = Path(output_filename).stem
        generated_clips = []
        for idx, img_path in enumerate(image_list):
            # Match image index to prompt index (fallback to the last prompt if we run out)
            current_prompt = (
                prompt_list[idx]
                if idx < len(prompt_list)
                else (prompt_list[-1] if prompt_list else "")
            )

            raw_clip_path = self.output_dir / f"raw_{stem}_{idx:02d}.mp4"
            if not force and output_is_valid(raw_clip_path):
                logger.info(
                    "   -> Image %d/%d already rendered — reusing %s",
                    idx + 1, len(image_list), raw_clip_path,
                )
                generated_clips.append(str(raw_clip_path))
                continue

            logger.info(
                f"   -> Rendering image {idx + 1}/{len(image_list)}: {img_path} with prompt: '{current_prompt}'"
            )
            clip = self._generate_single_clip(
                img_path, current_prompt, per_clip_duration, save_path=str(raw_clip_path)
            )
            if clip:
                generated_clips.append(clip)

        if not generated_clips:
            logger.error("Failed to generate any video clips.")
            return None

        # 2. Multiple images -> don't auto-combine. Park the raw clips in a
        # pending manifest and stop here; finalize_pending_video() combines
        # them once the frontend has reviewed and approved the set.
        if len(generated_clips) > 1:
            manifest_path = self._pending_manifest_path(output_filename)
            manifest = {
                "clip_paths": generated_clips,
                "target_audio_duration": target_audio_duration,
                "audio_path": audio_path,
                "output_filename": output_filename,
                "place_label": place_label,
            }
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            logger.info(
                "Waypoint has %d clips — combining deferred pending approval. "
                "Manifest written to %s. Call finalize_pending_video() once ready.",
                len(generated_clips),
                manifest_path,
            )
            return None

        # 3. Single image: fit duration, place at output_filename, upscale.
        # Narration audio is NOT muxed in here — see docstring.
        final_output = self._fit_and_finalize(
            generated_clips[0],
            target_audio_duration,
            output_filename,
            overshoot_tolerance=self._AUDIO_DURATION_TOLERANCE_SECONDS,
            place_label=place_label,
        )

        # Cleanup intermediate raw clip
        if os.path.exists(generated_clips[0]) and generated_clips[0] != final_output:
            try:
                os.remove(generated_clips[0])
            except OSError:
                pass

        logger.info(f"Waypoint video deliverable complete: {final_output}")
        return final_output