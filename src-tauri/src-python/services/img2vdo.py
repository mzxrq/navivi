"""
Image-to-Video Service for Attractions
----------------------------------------------------------------------------
Handles ComfyUI image-to-video batching, multi-image list detection,
concatenation via VideoEditor, and audio synchronization.
----------------------------------------------------------------------------
"""

import os
import json
import uuid
import requests
import websocket
from pathlib import Path
from typing import List, Union, Optional

from services.vdoeditor import VideoEditor
from services.job_config import JobConfigManager
from services.logger import setup_logger

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

        # Inject dynamic parameters
        workflow["11"]["inputs"]["image"] = comfy_filename
        workflow["69:56"]["inputs"]["text"] = prompt_text

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
            for media in outputs[node_id].get("videos", []):
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

        # Cleanup intermediate raw clips
        for clip in generated_clips:
            if os.path.exists(clip) and clip != final_output:
                try:
                    os.remove(clip)
                except OSError:
                    pass

        logger.info(f"Waypoint video deliverable complete: {final_output}")
        return final_output
