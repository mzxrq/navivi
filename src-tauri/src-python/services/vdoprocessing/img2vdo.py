"""
Image-to-Video Service for Attractions
----------------------------------------------------------------------------
Handles ComfyUI image-to-video batching, multi-image list detection,
concatenation via VideoEditor, and audio synchronization.
----------------------------------------------------------------------------
"""

import os
import json
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
        3. Combines multi-image clips via VideoEditor.
        4. Scales playback speed to match target_audio_duration (only if shorter).
        5. Muxes audio if provided.
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

        # 2. Combine together if there are multiple images in the list
        if len(generated_clips) > 1:
            logger.info(
                f"Combining {len(generated_clips)} clips into a sequence using VideoEditor..."
            )
            temp_combined_name = f"temp_concat_{uuid.uuid4().hex[:8]}.mp4"
            combined_video = self.editor.concatenate_videos(
                input_paths=generated_clips, output_filename=temp_combined_name
            )
        else:
            combined_video = generated_clips[0]

        # 3. Consider audio length: Ensure combined video is >= audio duration
        if target_audio_duration > 0:
            # Check current video duration before attempting to stretch it
            current_duration = self.editor.get_video_duration(combined_video)

            if current_duration < target_audio_duration:
                logger.info(
                    f"Video ({current_duration:.2f}s) is shorter than audio ({target_audio_duration:.2f}s). Adjusting duration..."
                )
                scaled_name = f"temp_scaled_{uuid.uuid4().hex[:8]}.mp4"
                fitted_video = self.editor.adjust_video_duration(
                    video_path=combined_video,
                    target_duration=target_audio_duration,
                    output_filename=scaled_name,
                )
            else:
                logger.info(
                    f"Video ({current_duration:.2f}s) is already longer than or equal to audio. No scaling needed."
                )
                fitted_video = combined_video
        else:
            fitted_video = combined_video

        # 4. Mux Audio track if provided
        if audio_path and os.path.exists(audio_path):
            logger.info("Muxing narration audio into waypoint video...")
            final_output = self.editor.mux_audio_to_video(
                video_path=fitted_video,
                audio_path=audio_path,
                output_filename=output_filename,
            )
        else:
            final_output = fitted_video

        # 5. Upscale to match the map/waypoint clips' resolution (CPU-only
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

        # Cleanup intermediate raw clips
        for clip in generated_clips:
            if os.path.exists(clip) and clip != final_output:
                try:
                    os.remove(clip)
                except OSError:
                    pass

        logger.info(f"Waypoint video deliverable complete: {final_output}")
        return final_output