"""ComfyUI-backed image-to-video client for attraction clips
(Wan2.2-TI2V-5B-Turbo-GGUF, Q6_K quant).

Talks to the bundled ComfyUI install at src-python/bin/ComfyUI over its
REST API (submit a workflow graph, poll for completion, download the
result) — same "auto-start a local server on first use" shape as
services/tts/ttsengine.py's IrodoriTTSClient, reusing its generic
idle_watchdog.py rather than duplicating it.

This is the feature that replaced local_pan_generator.py as the default
attraction-clip generator (see img2vdo.py's _generate_single_clip) — that
module remains as the automatic fallback if ComfyUI can't be reached or a
generation fails.
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Final, Optional
from urllib.parse import urlsplit

import httpx

from services.logger.logger import setup_logger
from services import tuning

logger = setup_logger("ComfyUII2VClient")


def _kill_process_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


# API-format graph (class_type + inputs, keyed by node id) captured from the
# official "Wan 2.2 5B Video Generation" ComfyUI template
# (video_wan2_2_5B_ti2v) with its UNETLoader swapped for ComfyUI-GGUF's
# UnetLoaderGGUF pointed at the Q6_K quant — see comfy_wan_test exploration.
# Values marked below are overwritten per-call; everything else (wiring,
# node types) must not change without re-deriving from a working template —
# see the comfy skill's "never hand-edit a workflow" rule.
_WORKFLOW_TEMPLATE: Dict[str, Any] = {
    "gguf_unet": {
        "inputs": {"unet_name": tuning.COMFYUI_UNET_NAME},
        "class_type": "UnetLoaderGGUF",
        "_meta": {"title": "Unet Loader (GGUF)"},
    },
    "38": {
        "inputs": {
            "clip_name": tuning.COMFYUI_CLIP_NAME,
            "type": "wan",
            "device": "default",
        },
        "class_type": "CLIPLoader",
        "_meta": {"title": "Load CLIP"},
    },
    "39": {
        "inputs": {"vae_name": tuning.COMFYUI_VAE_NAME},
        "class_type": "VAELoader",
        "_meta": {"title": "Load VAE"},
    },
    "48": {
        "inputs": {"shift": tuning.COMFYUI_MODEL_SHIFT, "model": ["gguf_unet", 0]},
        "class_type": "ModelSamplingSD3",
        "_meta": {"title": "ModelSamplingSD3"},
    },
    "56": {
        "inputs": {"image": None},  # set per-call: uploaded input filename
        "class_type": "LoadImage",
        "_meta": {"title": "Load Image"},
    },
    "55": {
        "inputs": {
            "width": tuning.COMFYUI_WIDTH,
            "height": tuning.COMFYUI_HEIGHT,
            "length": None,  # set per-call
            "batch_size": 1,
            "vae": ["39", 0],
            "start_image": ["56", 0],
        },
        "class_type": "Wan22ImageToVideoLatent",
        "_meta": {"title": "Wan22ImageToVideoLatent"},
    },
    "6": {
        "inputs": {"text": None, "clip": ["38", 0]},  # set per-call: positive prompt
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "CLIP Text Encode (Positive Prompt)"},
    },
    "7": {
        "inputs": {"text": tuning.COMFYUI_NEGATIVE_PROMPT, "clip": ["38", 0]},
        "class_type": "CLIPTextEncode",
        "_meta": {"title": "CLIP Text Encode (Negative Prompt)"},
    },
    "3": {
        "inputs": {
            "seed": None,  # set per-call: randomized
            "steps": tuning.COMFYUI_STEPS,
            "cfg": tuning.COMFYUI_CFG,
            "sampler_name": tuning.COMFYUI_SAMPLER,
            "scheduler": tuning.COMFYUI_SCHEDULER,
            "denoise": 1,
            "model": ["48", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["55", 0],
        },
        "class_type": "KSampler",
        "_meta": {"title": "KSampler"},
    },
    "8": {
        "inputs": {"samples": ["3", 0], "vae": ["39", 0]},
        "class_type": "VAEDecode",
        "_meta": {"title": "VAE Decode"},
    },
    "57": {
        "inputs": {
            "fps": tuning.COMFYUI_FPS,
            "bit_depth": "auto",
            "color_space": "sRGB",
            "images": ["8", 0],
        },
        "class_type": "CreateVideo",
        "_meta": {"title": "Create Video"},
    },
    "58": {
        "inputs": {
            "filename_prefix": None,  # set per-call: unique per request
            "format": "auto",
            "format.codec": "auto",
            "video": ["57", 0],
        },
        "class_type": "SaveVideo",
        "_meta": {"title": "Save Video"},
    },
}
_SAVE_VIDEO_NODE_ID: Final[str] = "58"


def _resolve_frame_length(duration_sec: float) -> int:
    """Wan wants a frame count of the form 4k+1. Rounds duration*fps to the
    nearest such value, clamped to a sane range."""
    raw = max(1, round(duration_sec * tuning.COMFYUI_FPS))
    k = round((raw - 1) / 4)
    length = 4 * k + 1
    return max(tuning.COMFYUI_MIN_FRAMES, min(tuning.COMFYUI_MAX_FRAMES, length))


def _resolve_motion_prompt(camera_pan_hint: Any) -> str:
    """camera_pans entries (attraction_step.py) are short keywords
    (panright/panleft/zoomin/zoomout/none) shared with
    local_pan_generator.py's _CAMERA_PAN_PRESETS — not descriptive prose.
    Anything not in that vocabulary (e.g. a waypoint label used as a
    fallback prompt) is treated as a scene description and given a generic
    motion suffix instead."""
    if isinstance(camera_pan_hint, list):
        camera_pan_hint = camera_pan_hint[0] if camera_pan_hint else None
    key = str(camera_pan_hint).strip().lower() if camera_pan_hint else ""

    if key in tuning.COMFYUI_CAMERA_PAN_PROMPTS:
        return tuning.COMFYUI_CAMERA_PAN_PROMPTS[key]
    if key:
        return f"{camera_pan_hint}, {tuning.COMFYUI_DEFAULT_MOTION_PROMPT}"
    return tuning.COMFYUI_DEFAULT_MOTION_PROMPT


class ComfyUII2VClient:
    """Handles communication with the bundled local ComfyUI server for
    attraction image-to-video generation."""

    _SERVER_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "bin" / "ComfyUI"
    _SERVER_VENV_PYTHON: Final[Path] = _SERVER_DIR / ".venv" / (
        "Scripts/python.exe" if os.name == "nt" else "bin/python"
    )
    _IDLE_WATCHDOG_SCRIPT: Final[Path] = (
        Path(__file__).resolve().parents[1] / "tts" / "idle_watchdog.py"
    )
    _ACTIVITY_FILE: Final[Path] = _SERVER_DIR / ".last_active_i2v"
    _POLL_INTERVAL_SECONDS: Final[float] = 2.0
    # Written with the spawning process's PID right after Popen — see
    # IrodoriTTSClient's identical mechanism in services/tts/ttsengine.py.
    _PIDFILE: Final[Path] = _SERVER_DIR / ".server.pid"

    # One server subprocess is enough for every client instance/caller in
    # this process, same reasoning as IrodoriTTSClient.
    _server_process: Optional[subprocess.Popen] = None

    def __init__(self, base_url: str = tuning.COMFYUI_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def _health_url(self) -> str:
        return f"{self.base_url}/system_stats"

    def _is_server_up(self) -> bool:
        try:
            with httpx.Client() as client:
                response = client.get(self._health_url(), timeout=3.0)
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True, timeout=5,
                )
                return str(pid) in result.stdout
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @classmethod
    def _other_process_is_starting_server(cls) -> bool:
        try:
            pid = int(cls._PIDFILE.read_text().strip())
        except (OSError, ValueError):
            return False
        return cls._pid_is_alive(pid)

    def _ensure_server_running(self) -> None:
        """Starts the bundled ComfyUI server as a subprocess if it isn't
        already reachable, then waits for it to come up. Raises
        RuntimeError if it can't be found/started or never becomes healthy
        in time — callers should catch this and fall back to
        local_pan_generator rather than hard-failing a waypoint."""
        if self._is_server_up():
            return

        if not self._SERVER_VENV_PYTHON.exists():
            raise RuntimeError(
                f"Bundled ComfyUI isn't reachable at {self.base_url} and its "
                f"venv wasn't found at {self._SERVER_VENV_PYTHON} to auto-start it."
            )

        if (
            ComfyUII2VClient._server_process is None
            or ComfyUII2VClient._server_process.poll() is not None
        ):
            if self._other_process_is_starting_server():
                logger.info(
                    "Another process is already starting the bundled ComfyUI "
                    "server — waiting for it instead of starting a second copy."
                )
            else:
                logger.info(
                    "Bundled ComfyUI not reachable at %s — starting it as a "
                    "subprocess...",
                    self.base_url,
                )
                port = urlsplit(self.base_url).port or 8189
                popen_kwargs: Dict[str, Any] = {}
                if os.name == "nt":
                    # CREATE_NO_WINDOW (not DETACHED_PROCESS) — a fully
                    # detached process has NO console at all, which some of
                    # ComfyUI's Fortran/MKL-linked dependencies (numpy/scipy)
                    # crash under on Windows ("forrtl: error (200): program
                    # aborting due to window-CLOSE event"). CREATE_NO_WINDOW
                    # still shows no visible window but keeps a (hidden)
                    # console allocated.
                    popen_kwargs["creationflags"] = (
                        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                    )
                else:
                    popen_kwargs["start_new_session"] = True
                log_path = self._SERVER_DIR / "comfyui_server.log"
                log_file = open(log_path, "ab")
                ComfyUII2VClient._server_process = subprocess.Popen(
                    [
                        str(self._SERVER_VENV_PYTHON), "main.py",
                        "--listen", "127.0.0.1", "--port", str(port),
                        "--disable-auto-launch",
                    ],
                    cwd=str(self._SERVER_DIR),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    **popen_kwargs,
                )
                self._PIDFILE.write_text(str(ComfyUII2VClient._server_process.pid))
                self._touch_activity()
                self._start_idle_watchdog(ComfyUII2VClient._server_process.pid)

        deadline = time.monotonic() + tuning.COMFYUI_SERVER_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._is_server_up():
                logger.info("Bundled ComfyUI is up at %s.", self.base_url)
                return
            if (
                ComfyUII2VClient._server_process is not None
                and ComfyUII2VClient._server_process.poll() is not None
            ):
                raise RuntimeError(
                    "Bundled ComfyUI subprocess exited while starting up — "
                    f"see {self._SERVER_DIR / 'comfyui_server.log'} for details."
                )
            time.sleep(1.0)

        raise RuntimeError(
            f"Bundled ComfyUI did not become healthy within "
            f"{tuning.COMFYUI_SERVER_START_TIMEOUT_SECONDS:.0f}s of starting."
        )

    @classmethod
    def stop_server(cls) -> None:
        """Explicitly terminates the ComfyUI server now, rather than
        waiting on its idle timeout — mirrors IrodoriTTSClient.stop_server."""
        if cls._server_process is not None and cls._server_process.poll() is None:
            logger.info(
                "Stopping bundled ComfyUI server (%s) to free its resources.",
                cls._server_process.pid,
            )
            _kill_process_tree(cls._server_process.pid)
            cls._server_process = None

    def clear_queue(self) -> None:
        """Interrupts whatever ComfyUI is currently running and clears its
        pending queue. Without this, a killed/restarted pipeline run leaves
        its in-flight job running server-side — the next run's job just
        gets queued behind it (and every restart after that queues another
        one), so a slow/stuck generation only ever gets slower across
        restarts instead of actually starting fresh. Best-effort: a
        freshly-started server with nothing queued yet is a no-op here."""
        if not self._is_server_up():
            return
        try:
            with httpx.Client() as client:
                client.post(f"{self.base_url}/interrupt", timeout=5.0)
                client.post(f"{self.base_url}/queue", json={"clear": True}, timeout=5.0)
            logger.info("Cleared any stale ComfyUI queue/in-flight job before starting.")
        except httpx.HTTPError as exc:
            logger.warning("Could not clear ComfyUI queue (%s) — continuing anyway.", exc)

    def _touch_activity(self) -> None:
        try:
            self._ACTIVITY_FILE.touch()
        except OSError:
            pass

    def _start_idle_watchdog(self, server_pid: int) -> None:
        popen_kwargs: Dict[str, Any] = {}
        if os.name == "nt":
            # See _ensure_server_running's comment on CREATE_NO_WINDOW vs
            # DETACHED_PROCESS above.
            popen_kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
            )
        else:
            popen_kwargs["start_new_session"] = True
        subprocess.Popen(
            [
                sys.executable, str(self._IDLE_WATCHDOG_SCRIPT),
                str(server_pid), str(self._ACTIVITY_FILE),
                str(tuning.COMFYUI_IDLE_TIMEOUT_SECONDS),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_kwargs,
        )

    def _upload_image(self, client: httpx.Client, image_path: str) -> str:
        """Uploads a local image into ComfyUI's input directory so a
        LoadImage node can reference it by name. Returns the server-side
        filename (ComfyUI de-dupes/renames on collision)."""
        with open(image_path, "rb") as f:
            files = {"image": (Path(image_path).name, f, "image/png")}
            response = client.post(
                f"{self.base_url}/upload/image", files=files, timeout=60.0
            )
        response.raise_for_status()
        data = response.json()
        return data["name"]

    def _build_graph(
        self,
        uploaded_image_name: str,
        prompt_text: str,
        length: int,
        filename_prefix: str,
    ) -> Dict[str, Any]:
        graph = copy.deepcopy(_WORKFLOW_TEMPLATE)
        graph["56"]["inputs"]["image"] = uploaded_image_name
        graph["55"]["inputs"]["length"] = length
        graph["6"]["inputs"]["text"] = prompt_text
        graph["3"]["inputs"]["seed"] = uuid.uuid4().int & 0xFFFFFFFFFFFF
        graph["58"]["inputs"]["filename_prefix"] = filename_prefix
        return graph

    def _submit(self, client: httpx.Client, graph: Dict[str, Any]) -> str:
        client_id = str(uuid.uuid4())
        response = client.post(
            f"{self.base_url}/prompt",
            json={"prompt": graph, "client_id": client_id},
            timeout=30.0,
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"ComfyUI rejected the workflow ({response.status_code}): {response.text}"
            )
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"ComfyUI workflow validation failed: {data['error']}")
        return data["prompt_id"]

    def _wait_for_result(self, client: httpx.Client, prompt_id: str) -> Dict[str, Any]:
        deadline = time.monotonic() + tuning.COMFYUI_GENERATION_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            response = client.get(f"{self.base_url}/history/{prompt_id}", timeout=30.0)
            response.raise_for_status()
            history = response.json()
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error" or any(
                    m[0] == "execution_error" for m in status.get("messages", [])
                ):
                    raise RuntimeError(
                        f"ComfyUI execution failed for prompt {prompt_id}: "
                        f"{status.get('messages')}"
                    )
                outputs = entry.get("outputs", {})
                if _SAVE_VIDEO_NODE_ID in outputs:
                    return outputs[_SAVE_VIDEO_NODE_ID]
            time.sleep(self._POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"ComfyUI generation for prompt {prompt_id} did not finish within "
            f"{tuning.COMFYUI_GENERATION_TIMEOUT_SECONDS:.0f}s."
        )

    def _download_video(
        self, client: httpx.Client, video_info: Dict[str, Any], output_path: str
    ) -> None:
        params = {
            "filename": video_info["filename"],
            "subfolder": video_info.get("subfolder", ""),
            "type": video_info.get("type", "output"),
        }
        response = client.get(f"{self.base_url}/view", params=params, timeout=120.0)
        response.raise_for_status()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(response.content)

    def generate_clip(
        self,
        image_path: str,
        output_path: str,
        duration_sec: float,
        camera_pan_hint: Any = None,
    ) -> str:
        """Generates one attraction clip via the bundled ComfyUI server
        (Wan2.2-TI2V-5B-Turbo-GGUF Q6_K image-to-video) and saves it to
        output_path. Raises on any failure (server unreachable, execution
        error, timeout) — callers should catch and fall back to
        local_pan_generator.generate_local_clip."""
        self._ensure_server_running()

        length = _resolve_frame_length(duration_sec)
        prompt_text = _resolve_motion_prompt(camera_pan_hint)
        filename_prefix = f"attraction/{uuid.uuid4().hex[:8]}"

        with httpx.Client() as client:
            uploaded_name = self._upload_image(client, image_path)
            graph = self._build_graph(uploaded_name, prompt_text, length, filename_prefix)
            prompt_id = self._submit(client, graph)
            logger.info(
                "Submitted ComfyUI I2V job %s (length=%d frames, prompt=%r)",
                prompt_id, length, prompt_text,
            )
            video_outputs = self._wait_for_result(client, prompt_id)
            self._touch_activity()

            # SaveVideo reports its output under "videos" on some ComfyUI
            # versions and "images" (with animated=[true]) on others — check
            # all the shapes actually seen rather than assuming one.
            videos = (
                video_outputs.get("videos")
                or video_outputs.get("gifs")
                or video_outputs.get("images")
            )
            if not videos:
                raise RuntimeError(
                    f"ComfyUI job {prompt_id} completed but produced no video output."
                )
            self._download_video(client, videos[0], output_path)

        logger.info("ComfyUI I2V clip saved to %s", output_path)
        return output_path
