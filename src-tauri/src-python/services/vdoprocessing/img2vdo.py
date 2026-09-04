"""
Image-to-Video Service for Attractions
----------------------------------------------------------------------------
Handles ComfyUI image-to-video batching, multi-image list detection,
concatenation via VideoEditor, and audio synchronization.
----------------------------------------------------------------------------
"""

import os
import json
import shutil
import subprocess
import time
import uuid
import requests
import websocket
from pathlib import Path
from typing import Any, Dict, Final, List, Union, Optional

from services.vdoprocessing.vdoeditor import VideoEditor
from services.vdoprocessing.vdoexporter import VideoExporter
from services.config.job_config import JobConfigManager
from services.logger.logger import setup_logger

# Logging configuration
logger = setup_logger("AttractionVideoGenerator")

COMFY_API_URL = "http://127.0.0.1:8188"


# [Core] AttractionVideoGenerator Class
class AttractionVideoGenerator:
    """Manages Image-to-Video generation and synchronization for attractions."""

    # [Config] Initialize with JobConfigManager and workflow configuration
    def __init__(
        self,
        job_config: Optional[JobConfigManager] = None,
        workflow_config_path: str = "assets/config/img2vdo-api.json",
    ):
        self.config = job_config or JobConfigManager()
        self.editor = VideoEditor(job_config=self.config)
        self.workflow_config_path = workflow_config_path

        # Route outputs to project video directory
        base_dir = Path(self.config.get("directory_path", "assets"))
        self.output_dir = (base_dir / "video").resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # bin/ComfyUI now has its actual application files checked out (plus its
    # own already-synced .venv), same shape as bin/Irodori-TTS-Server — so
    # it can be auto-started the same way instead of just failing with a
    # "start it yourself" error.
    _COMFY_DIR: Final[Path] = (
        Path(__file__).resolve().parents[2] / "bin" / "ComfyUI"
    )
    _COMFY_VENV_PYTHON: Final[Path] = _COMFY_DIR / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    # Generous: first run also loads custom nodes / models, which can take
    # a while — giving up too early on a legitimately slow first start is a
    # worse failure mode than this just taking longer.
    _COMFY_START_TIMEOUT_SECONDS: Final[float] = 300.0
    _COMFY_POLL_INTERVAL_SECONDS: Final[float] = 1.0

    # Class-level: one ComfyUI subprocess is enough for every
    # AttractionVideoGenerator instance in this process.
    _comfy_process: Optional[subprocess.Popen] = None

    # Matches mapfetcher.py's MapFetcher.fetch_image/process_residential_sequence
    # default output_size — the resolution the map/waypoint clips actually
    # render at. ComfyUI attraction clips are generated smaller (currently
    # 1280x704) to fit the 8GB VRAM budget; upscaling here keeps every clip
    # the same resolution before subtitle burning, since nothing downstream
    # in the pipeline reconciles mismatched clip sizes.
    _TARGET_WIDTH: Final[int] = 1920
    _TARGET_HEIGHT: Final[int] = 1080

    # Audio/video duration mismatch tolerance. Multi-image waypoints
    # concatenate several fixed-length ComfyUI clips together (e.g. 2 x 7s
    # = 14s), which can run far past a short narration — left uncorrected,
    # that mismatch reaches the downstream timeline/NLE step, which pads
    # the gap by freezing on the last frame until the narration ends.
    # Single-image waypoints get the same general tolerance; multi-image
    # ones get a tighter overshoot cap since concatenation compounds error.
    _AUDIO_DURATION_TOLERANCE_SECONDS: Final[float] = 3.0
    _MULTI_IMAGE_OVERSHOOT_TOLERANCE_SECONDS: Final[float] = 2.0

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

    # [Core] Called at the start of a fresh generate for a waypoint (the
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

    @staticmethod
    def _is_comfy_up() -> bool:
        try:
            requests.get(f"{COMFY_API_URL}/system_stats", timeout=3.0)
            return True
        except requests.exceptions.RequestException:
            return False

    # [IO] Starts ComfyUI as a subprocess if it isn't already reachable, and
    # waits for it to come up, instead of failing outright.
    def _ensure_comfy_reachable(self) -> None:
        """Checked once up front (before generating any clips) so a
        missing/not-yet-started ComfyUI is handled here — auto-started and
        waited for — instead of surfacing later as a raw connection-refused
        error from partway through an image upload or an open websocket."""
        if self._is_comfy_up():
            return

        if not self._COMFY_VENV_PYTHON.exists():
            raise RuntimeError(
                f"ComfyUI isn't reachable at {COMFY_API_URL} and its bundled "
                f"venv wasn't found at {self._COMFY_VENV_PYTHON} to auto-start "
                "it. Set it up (see bin/ComfyUI), or start it manually."
            )

        if (
            AttractionVideoGenerator._comfy_process is None
            or AttractionVideoGenerator._comfy_process.poll() is not None
        ):
            logger.info(
                "ComfyUI not reachable at %s — starting it as a subprocess "
                "(this can take a while on first run while it loads custom "
                "nodes/models)...",
                COMFY_API_URL,
            )
            popen_kwargs: Dict[str, Any] = {}
            if os.name == "nt":
                # Detached from this console/process group so it outlives a
                # short-lived pipeline run instead of being torn down (or
                # fighting over Ctrl+C) with it — same as IrodoriTTSClient.
                popen_kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
                )
            else:
                popen_kwargs["start_new_session"] = True
            log_path = self._COMFY_DIR / "server.log"
            log_file = open(log_path, "ab")
            AttractionVideoGenerator._comfy_process = subprocess.Popen(
                [str(self._COMFY_VENV_PYTHON), "main.py"],
                cwd=str(self._COMFY_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                **popen_kwargs,
            )

        deadline = time.monotonic() + self._COMFY_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._is_comfy_up():
                logger.info("ComfyUI is up at %s.", COMFY_API_URL)
                return
            if AttractionVideoGenerator._comfy_process.poll() is not None:
                raise RuntimeError(
                    "ComfyUI subprocess exited while starting up — see "
                    f"{self._COMFY_DIR / 'server.log'} for details."
                )
            time.sleep(self._COMFY_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"ComfyUI did not become reachable within "
            f"{self._COMFY_START_TIMEOUT_SECONDS:.0f}s of starting."
        )

    # [IO] Uploads an image to ComfyUI server input directory
    def _upload_image(self, local_path: str) -> str:
        """Uploads an image to ComfyUI server input directory."""
        url = f"{COMFY_API_URL}/upload/image"
        with open(local_path, "rb") as f:
            files = {"image": f}
            data = {"type": "input", "overwrite": "true"}
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            return response.json()["name"]

    # [Core/Animation] Generates a single video clip from an image and prompt using ComfyUI
    def _generate_single_clip(
        self, local_image_path: str, prompt_text: str
    ) -> Optional[str]:
        """Runs the ComfyUI workflow for a single image and downloads the resulting clip."""
        comfy_filename = self._upload_image(local_image_path)

        with open(self.workflow_config_path, "r", encoding="utf-8") as f:
            workflow = json.load(f)

        # Inject dynamic parameters — node IDs specific to
        # assets/config/img2vdo-api.json's current LTX-2 image+audio-to-
        # video graph: "269" is its only LoadImage node, and "320:319"
        # (PrimitiveStringMultiline) is the raw prompt text that feeds BOTH
        # the direct path and 320:325's LLM prompt-enhancer, so it takes
        # effect regardless of "320:328" (the "Enable Prompt Enhance"
        # switch's) current state — unlike injecting into 320:325 itself,
        # which only has any effect when that switch is on. Enhancement is
        # off by default here: the gemma-3-12b enhancer model doesn't fit
        # in 8GB VRAM either, so each token of its output takes ~2s+ from
        # the same CPU/GPU swap-thrashing as the video model — turning it
        # back on (320:328 -> true) costs several extra minutes per clip.
        workflow["269"]["inputs"]["image"] = comfy_filename
        # Force visible camera motion on every clip: at low step counts /
        # Q2_K quantization the model defaults to near-static output unless
        # the prompt explicitly demands movement (confirmed by comparing
        # frames of a generated clip — statue/background were frozen aside
        # from mist drift). Appended rather than left to each prompt source
        # (waypoint camera_pans, fallback label) so it applies unconditionally.
        workflow["320:319"]["inputs"]["value"] = (
            f"{prompt_text} Camera must pan smoothly and continuously "
            f"throughout the shot, clearly visible motion, not a static shot."
        )

        client_id = str(uuid.uuid4())
        ws = websocket.WebSocket()
        ws.connect(f"ws://127.0.0.1:8188/ws?clientId={client_id}")

        payload = {"prompt": workflow, "client_id": client_id}
        res = requests.post(f"{COMFY_API_URL}/prompt", json=payload).json()

        if "error" in res:
            logger.error(f"ComfyUI Error: {res['error']}")
            ws.close()
            return None

        prompt_id = res.get("prompt_id")

        while True:
            out = ws.recv()
            if isinstance(out, str):
                msg = json.loads(out)
                if msg["type"] == "executing":
                    data = msg["data"]
                    if data["node"] is None and data.get("prompt_id") == prompt_id:
                        break
                elif msg["type"] == "execution_error":
                    if msg["data"].get("prompt_id") == prompt_id:
                        logger.error(f"Execution Error: {msg['data']}")
                        break
        ws.close()

        # Download result
        history = requests.get(f"{COMFY_API_URL}/history/{prompt_id}").json()
        if prompt_id not in history:
            return None

        outputs = history[prompt_id]["outputs"]
        for node_id in outputs:
            node_output = outputs[node_id]
            # ComfyUI's SaveVideo node (see comfy_api/latest/_ui.py's
            # PreviewVideo.as_dict, used by assets/config/img2vdo-api.json's
            # "333" SaveVideo node) reports its result under "images" (with
            # "animated": true) — NOT "videos", which some older/other
            # video-producing nodes use instead. Checking "videos" alone
            # silently returned no clip at all even though ComfyUI had
            # actually rendered one successfully. Checked in this order
            # since "images" is what the currently bundled workflow uses.
            media_list = node_output.get("images") or node_output.get("videos") or []
            for media in media_list:
                view_url = f"{COMFY_API_URL}/view"
                params = {
                    "filename": media["filename"],
                    "subfolder": media.get("subfolder", ""),
                    "type": "output",
                }
                resp = requests.get(view_url, params=params)

                save_path = (
                    self.output_dir / f"raw_{uuid.uuid4().hex[:6]}_{media['filename']}"
                )
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                return str(save_path)

        return None

    # [Core] Shared tail end of clip processing: fit duration, place at the
    # project's output path, and upscale. Used by both the single-image path
    # in process_attraction_video and finalize_pending_video's multi-image
    # path, so the two stay in sync instead of drifting apart.
    def _fit_and_finalize(
        self,
        video_path: str,
        target_audio_duration: float,
        output_filename: str,
        overshoot_tolerance: float,
    ) -> str:
        """Trims/stretches video_path to within tolerance of
        target_audio_duration, writes the result to output_filename in the
        project's video directory, then upscales it. Narration audio is
        intentionally NOT muxed in here — see process_attraction_video's
        docstring for why."""
        if target_audio_duration > 0:
            current_duration = self.editor.get_video_duration(video_path)
            diff = current_duration - target_audio_duration

            if diff > overshoot_tolerance:
                logger.info(
                    f"Video ({current_duration:.2f}s) exceeds audio ({target_audio_duration:.2f}s) "
                    f"by more than {overshoot_tolerance:.1f}s. Trimming to fit..."
                )
                trimmed_name = f"temp_trimmed_{uuid.uuid4().hex[:8]}.mp4"
                fitted_video = self.editor.trim_video_duration(
                    video_path=video_path,
                    target_duration=target_audio_duration,
                    output_filename=trimmed_name,
                )
            elif -diff > self._AUDIO_DURATION_TOLERANCE_SECONDS:
                logger.info(
                    f"Video ({current_duration:.2f}s) is shorter than audio ({target_audio_duration:.2f}s) "
                    f"by more than {self._AUDIO_DURATION_TOLERANCE_SECONDS:.1f}s. Adjusting duration..."
                )
                scaled_name = f"temp_scaled_{uuid.uuid4().hex[:8]}.mp4"
                fitted_video = self.editor.adjust_video_duration(
                    video_path=video_path,
                    target_duration=target_audio_duration,
                    output_filename=scaled_name,
                )
            else:
                logger.info(
                    f"Video ({current_duration:.2f}s) is within tolerance of audio "
                    f"({target_audio_duration:.2f}s). No adjustment needed."
                )
                fitted_video = video_path
        else:
            fitted_video = video_path

        # Place at the proper output_filename path — previously this was a
        # side effect of mux_audio_to_video; now done explicitly since
        # muxing narration audio in is deferred (see docstring above).
        final_path = self.editor._resolve_output_path(output_filename, "video")
        if Path(fitted_video).resolve() != final_path.resolve():
            if final_path.exists():
                final_path.unlink()
            shutil.copy2(fitted_video, final_path)
        final_output = str(final_path)

        # Upscale to match the map/waypoint clips' resolution (CPU-only
        # ffmpeg lanczos scale — no VRAM cost, so this is safe on 8GB cards
        # regardless of what generation already used). Written to a temp
        # file then swapped in, since ffmpeg can't write to its own input.
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

        return final_output

    # [Core/Animation] Combines previously-generated attraction clips into
    # one waypoint video, once the frontend has reviewed and approved them.
    def finalize_pending_video(
        self,
        clip_paths: List[str],
        target_audio_duration: float,
        output_filename: str,
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

        if len(valid_clips) > 1:
            logger.info(
                f"Combining {len(valid_clips)} approved clips into a sequence..."
            )
            temp_combined_name = f"temp_concat_{uuid.uuid4().hex[:8]}.mp4"
            combined_video = self.editor.concatenate_videos(
                input_paths=valid_clips, output_filename=temp_combined_name
            )
            overshoot_tolerance = self._MULTI_IMAGE_OVERSHOOT_TOLERANCE_SECONDS
        else:
            combined_video = valid_clips[0]
            overshoot_tolerance = self._AUDIO_DURATION_TOLERANCE_SECONDS

        final_output = self._fit_and_finalize(
            combined_video, target_audio_duration, output_filename, overshoot_tolerance
        )

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

    # [Core/Animation] Main processing function for attraction video generation
    def process_attraction_video(
        self,
        popup_image_entry: Union[str, List[str], None],
        prompt_text: Union[str, List[str]],
        target_audio_duration: float,
        audio_path: Optional[str] = None,
        output_filename: str = "waypoint_final.mp4",
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

        # Regenerating this waypoint — clear out whatever a previous run
        # left behind (old deliverable, old pending manifest + its clips)
        # before doing any fresh work.
        self._clear_stale_outputs(output_filename)

        self._ensure_comfy_reachable()

        # --- Check list vs string for prompts ---
        if isinstance(prompt_text, str):
            prompt_list = [prompt_text]
        elif isinstance(prompt_text, list):
            prompt_list = prompt_text
        else:
            prompt_list = [""]

        logger.info(f"Processing waypoint with {len(image_list)} image(s)...")

        # 1. Generate video clips for each image
        generated_clips = []
        for idx, img_path in enumerate(image_list):
            # Match image index to prompt index (fallback to the last prompt if we run out)
            current_prompt = (
                prompt_list[idx]
                if idx < len(prompt_list)
                else (prompt_list[-1] if prompt_list else "")
            )

            logger.info(
                f"   -> Rendering image {idx + 1}/{len(image_list)}: {img_path} with prompt: '{current_prompt}'"
            )
            clip = self._generate_single_clip(img_path, current_prompt)
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
        )

        # Cleanup intermediate raw clip
        if os.path.exists(generated_clips[0]) and generated_clips[0] != final_output:
            try:
                os.remove(generated_clips[0])
            except OSError:
                pass

        logger.info(f"Waypoint video deliverable complete: {final_output}")
        return final_output