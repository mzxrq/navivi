"""ComfyUI-backed image-to-video client for attraction clips
(Wan2.2 GGUF: TI2V-5B-Turbo or the I2V-A14B pair - see tuning.COMFYUI_MODEL).

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
import math
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Final, List, Optional, Tuple
from urllib.parse import urlsplit

import httpx

from services.logger.logger import setup_logger
from services.logger.progress import tracker
from services import tuning

logger = setup_logger("ComfyUII2VClient")


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TQDM_RE = re.compile(r"(\d+)%\|.*?\|\s*(\d+)/(\d+)\s*\[([\d:]+)<([\d:?]+)")
_PHASES = (
    ("Requested to load WAN22", "loading model"),
    ("Requested to load WanTEModel", "loading text encoder"),
    ("Model Initializing", "initializing model"),
    ("Requested to load WanVAE", "VAE decode"),
)
_PROBLEM_RE = re.compile(r"\[(WARNING|ERROR|CRITICAL)\]|Traceback|Error|Exception")


class _ServerLogTail:
    """New complete lines appended to ComfyUI's server log since creation."""

    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            self.offset = self.path.stat().st_size
        except OSError:
            self.offset = 0
        self._partial = b""

    def poll(self) -> List[str]:
        try:
            with open(self.path, "rb") as f:
                f.seek(self.offset)
                data = f.read()
        except OSError:
            return []
        if not data:
            return []
        self.offset += len(data)
        data = self._partial + data
        cut = max(data.rfind(b"\n"), data.rfind(b"\r"))
        self._partial = data[cut + 1:]
        text = _ANSI_RE.sub("", data[:cut + 1].decode("utf-8", errors="replace"))
        return [line.rstrip() for line in re.split(r"[\r\n]+", text) if line.strip()]


class _ServerLogReporter:
    """Turns ComfyUI log lines into the CLI status line (progress/phase) and
    persistent notes (warnings, errors, tracebacks)."""

    def __init__(self, label: str):
        self.label = label
        self._last_shown: Optional[str] = None
        self._in_traceback = False

    def show(self, text: str) -> None:
        text = f"{self.label} · {text}"
        if text != self._last_shown:
            self._last_shown = text
            tracker.show(text)

    def _note(self, line: str) -> None:
        tracker.note(f"[ComfyUI] {line}")
        logger.warning("[ComfyUI] %s", line.strip())
        self._last_shown = None

    def report(self, lines: List[str]) -> None:
        for line in lines:
            m = _TQDM_RE.search(line)
            if m:
                self._in_traceback = False
                done, total, eta = m.group(2), m.group(3), m.group(5)
                suffix = f" · ETA {eta}" if eta != "?" and done != total else ""
                self.show(f"step {done}/{total}{suffix}")
                continue
            if line.startswith("Traceback"):
                self._in_traceback = True
            elif self._in_traceback and not line[0].isspace() and not line.startswith("During handling"):
                # The unindented "XxxError: ..." line closes the traceback.
                self._in_traceback = False
                self._note(line)
                continue
            if self._in_traceback or _PROBLEM_RE.search(line):
                self._note(line)
                continue
            for needle, phase in _PHASES:
                if needle in line:
                    self.show(phase)
                    break




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
    # Tiled, not plain VAEDecode: decoding all frames at full size in one
    # pass needs more VRAM than an 8 GB card has left with the Wan model still
    # loaded, spills into system RAM and takes 10+ minutes per clip; in
    # tiles/frame chunks it fits (see tuning.COMFYUI_VAE_TILE_*).
    "8": {
        "inputs": {
            "samples": ["3", 0], "vae": ["39", 0],
            "tile_size": tuning.COMFYUI_VAE_TILE_SIZE,
            "overlap": tuning.COMFYUI_VAE_TILE_OVERLAP,
            "temporal_size": tuning.COMFYUI_VAE_TEMPORAL_SIZE,
            "temporal_overlap": tuning.COMFYUI_VAE_TEMPORAL_OVERLAP,
        },
        "class_type": "VAEDecodeTiled",
        "_meta": {"title": "VAE Decode (Tiled)"},
    },
    "57": {
        "inputs": {
            "fps": tuning.COMFYUI_GEN_FPS,
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


def _a14b_expert(unet_name: str, lora_name: str) -> Dict[str, Any]:
    return {
        "unet": {"inputs": {"unet_name": unet_name}, "class_type": "UnetLoaderGGUF"},
        "lora": {"inputs": {"lora_name": lora_name, "strength_model": 1.0}, "class_type": "LoraLoaderModelOnly"},
        "shift": {"inputs": {"shift": tuning.COMFYUI_MODEL_SHIFT}, "class_type": "ModelSamplingSD3"},
    }


def _a14b_template() -> Dict[str, Any]:
    """Wiring from ComfyUI's "Wan 2.2 14B I2V" template (video_wan2_2_14B_i2v)
    with its 4-step Lightx2v path on: the high-noise expert samples steps
    0..COMFYUI_A14B_SPLIT_STEP and hands its noisy latent to the low-noise
    one. UNETLoader swapped for UnetLoaderGGUF, VAEDecode for the tiled one."""
    graph: Dict[str, Any] = {}
    for tag, unet, lora in (
        ("high", tuning.COMFYUI_A14B_HIGH_UNET_NAME, tuning.COMFYUI_A14B_HIGH_LORA_NAME),
        ("low", tuning.COMFYUI_A14B_LOW_UNET_NAME, tuning.COMFYUI_A14B_LOW_LORA_NAME),
    ):
        nodes = _a14b_expert(unet, lora)
        nodes["lora"]["inputs"]["model"] = [f"unet_{tag}", 0]
        nodes["shift"]["inputs"]["model"] = [f"lora_{tag}", 0]
        graph.update({f"{name}_{tag}": node for name, node in nodes.items()})
    for node_id in ("38", "56", "6", "7", "8", "57", "58"):
        graph[node_id] = copy.deepcopy(_WORKFLOW_TEMPLATE[node_id])
    graph["39"] = {"inputs": {"vae_name": tuning.COMFYUI_VAE_NAME}, "class_type": "VAELoader"}
    graph["55"] = {
        "inputs": {
            "width": tuning.COMFYUI_WIDTH,
            "height": tuning.COMFYUI_HEIGHT,
            "length": None,  # set per-call
            "batch_size": 1,
            "positive": ["6", 0],
            "negative": ["7", 0],
            "vae": ["39", 0],
            "start_image": ["56", 0],
        },
        "class_type": "WanImageToVideo",
    }
    sampler = {
        "steps": tuning.COMFYUI_STEPS,
        "cfg": tuning.COMFYUI_CFG,
        "sampler_name": tuning.COMFYUI_SAMPLER,
        "scheduler": tuning.COMFYUI_SCHEDULER,
        "positive": ["55", 0],
        "negative": ["55", 1],
    }
    graph["3"] = {
        "inputs": {
            **sampler,
            "add_noise": "enable",
            "noise_seed": None,  # set per-call: randomized
            "start_at_step": 0,
            "end_at_step": tuning.COMFYUI_A14B_SPLIT_STEP,
            "return_with_leftover_noise": "enable",
            "model": ["shift_high", 0],
            "latent_image": ["55", 2],
        },
        "class_type": "KSamplerAdvanced",
    }
    graph["3_low"] = {
        "inputs": {
            **sampler,
            "add_noise": "disable",
            "noise_seed": 0,
            "start_at_step": tuning.COMFYUI_A14B_SPLIT_STEP,
            "end_at_step": tuning.COMFYUI_STEPS,
            "return_with_leftover_noise": "disable",
            "model": ["shift_low", 0],
            "latent_image": ["3", 0],
        },
        "class_type": "KSamplerAdvanced",
    }
    graph["8"]["inputs"]["samples"] = ["3_low", 0]
    graph["57"]["inputs"]["fps"] = tuning.COMFYUI_GEN_FPS
    return graph


def _fun_camera_template() -> Dict[str, Any]:
    """Wiring from ComfyUI's "Wan2.1 Fun Camera 1.3B" template
    (video_wan2.1_fun_camera_v1.1_1.3B): WanCameraEmbedding turns the preset
    into a camera path, WanCameraImageToVideo conditions on it plus a
    CLIP-vision encoding of the photo. VAEDecode swapped for the tiled one."""
    graph = {k: copy.deepcopy(_WORKFLOW_TEMPLATE[k]) for k in ("38", "56", "6", "7", "3", "8", "57", "58")}
    graph["unet"] = {
        "inputs": {"unet_name": tuning.COMFYUI_FUN_CAMERA_UNET_NAME, "weight_dtype": "default"},
        "class_type": "UNETLoader",
    }
    graph["48"] = {"inputs": {"shift": tuning.COMFYUI_MODEL_SHIFT, "model": ["unet", 0]}, "class_type": "ModelSamplingSD3"}
    graph["39"] = {"inputs": {"vae_name": tuning.COMFYUI_VAE_NAME}, "class_type": "VAELoader"}
    graph["clip_vision"] = {"inputs": {"clip_name": tuning.COMFYUI_CLIP_VISION_NAME}, "class_type": "CLIPVisionLoader"}
    graph["clip_vision_encode"] = {
        "inputs": {"crop": "none", "clip_vision": ["clip_vision", 0], "image": ["56", 0]},
        "class_type": "CLIPVisionEncode",
    }
    graph["camera"] = {
        "inputs": {
            "camera_pose": None,  # set per-call
            "width": tuning.COMFYUI_WIDTH,
            "height": tuning.COMFYUI_HEIGHT,
            "length": None,  # set per-call
            "speed": tuning.COMFYUI_FUN_CAMERA_SPEED,
            "fx": 0.5, "fy": 0.5, "cx": 0.5, "cy": 0.5,
        },
        "class_type": "WanCameraEmbedding",
    }
    graph["55"] = {
        "inputs": {
            "batch_size": 1,
            "positive": ["6", 0],
            "negative": ["7", 0],
            "vae": ["39", 0],
            "clip_vision_output": ["clip_vision_encode", 0],
            "start_image": ["56", 0],
            "camera_conditions": ["camera", 0],
            "width": ["camera", 1],
            "height": ["camera", 2],
            "length": ["camera", 3],
        },
        "class_type": "WanCameraImageToVideo",
    }
    graph["3"]["inputs"].update({
        "model": ["48", 0], "positive": ["55", 0], "negative": ["55", 1], "latent_image": ["55", 2],
    })
    graph["57"]["inputs"]["fps"] = tuning.COMFYUI_GEN_FPS
    return graph


def _resolve_camera_pose(camera_pan_hint: Any) -> str:
    from services.vdoprocessing.camera_pan import normalize_camera_pan

    return tuning.COMFYUI_FUN_CAMERA_POSES.get(normalize_camera_pan(camera_pan_hint), "Static")


def _is_a14b() -> bool:
    return tuning.COMFYUI_MODEL == "a14b"


def _chains_only() -> bool:
    """Only the 5B graph can be unrolled into one multi-segment job."""
    return tuning.COMFYUI_MODEL != "5b"


def _resolve_frame_length(duration_sec: float) -> int:
    """Wan wants a frame count of the form 4k+1. Rounds duration*fps to the
    nearest such value, clamped to a sane range."""
    raw = max(1, round(duration_sec * tuning.COMFYUI_GEN_FPS))
    k = round((raw - 1) / 4)
    length = 4 * k + 1
    return max(tuning.COMFYUI_MIN_FRAMES, min(tuning.COMFYUI_MAX_FRAMES, length))


def _resolve_segments(duration_sec: float) -> Tuple[int, int]:
    """(segment count, frames per segment) for a clip of duration_sec. One
    segment sized to the duration when it fits in COMFYUI_MAX_FRAMES;
    otherwise full-length segments, as many as the duration needs - capped at
    tuning.COMFYUI_EXTEND_MAX_SEGMENTS, or uncapped (chains the whole
    narration) when that's None."""
    one = _resolve_frame_length(duration_sec)
    segment_sec = tuning.COMFYUI_MAX_FRAMES / tuning.COMFYUI_GEN_FPS
    cap = tuning.COMFYUI_EXTEND_MAX_SEGMENTS
    if duration_sec <= segment_sec or cap == 1:
        return 1, one
    count = math.ceil(duration_sec / segment_sec)
    if cap is not None:
        count = min(cap, count)
    return count, tuning.COMFYUI_MAX_FRAMES


def _resolve_motion_prompt(camera_pan_hint: Any) -> str:
    """camera_pans entries (attraction_step.py) are short keywords
    (panright/panleft/zoomin/zoomout/none) shared with
    local_pan_generator.py's _CAMERA_PAN_PRESETS — not descriptive prose.
    Anything not in that vocabulary (e.g. a waypoint label used as a
    fallback prompt) is treated as a scene description and given a generic
    motion suffix instead."""
    from services.vdoprocessing.camera_pan import normalize_camera_pan

    if isinstance(camera_pan_hint, list):
        camera_pan_hint = camera_pan_hint[0] if camera_pan_hint else None
    # "zoom-in" / "Zoom In" / "zoom_in" all mean the "zoomin" preset.
    key = normalize_camera_pan(camera_pan_hint)

    if key in tuning.COMFYUI_CAMERA_PAN_PROMPTS:
        return tuning.COMFYUI_CAMERA_PAN_PROMPTS[key]
    if key:
        return f"{camera_pan_hint}, {tuning.COMFYUI_DEFAULT_MOTION_PROMPT}"
    return tuning.COMFYUI_DEFAULT_MOTION_PROMPT


def _read_image(path: str):
    """cv2.imread that also opens a non-ASCII Windows path."""
    import cv2
    import numpy as np

    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    return image


def _edge_cropped(image_path: str, output_png: str) -> str:
    """image_path with tuning.COMFYUI_INPUT_EDGE_CROP trimmed off every edge,
    as output_png; image_path itself when there's nothing to trim."""
    import cv2
    import numpy as np

    crop = tuning.COMFYUI_INPUT_EDGE_CROP
    image = _read_image(image_path) if crop > 0 else None
    if image is None:
        return image_path
    h, w = image.shape[:2]
    dy, dx = round(h * crop), round(w * crop)
    ok, buffer = cv2.imencode(".png", image[dy:h - dy, dx:w - dx])
    if not ok:
        return image_path
    np.asarray(buffer).tofile(output_png)
    return output_png


def _write_last_frame(video_path: str, photo_path: str, output_png: str) -> str:
    """Writes the LAST frame of video_path to output_png, its colours pulled
    back to photo_path first (tuning.COMFYUI_CHAIN_COLOR_MATCH) so the next
    segment starts from the photo own grade instead of inheriting the grading
    Wan added - which is what makes the drift compound."""
    import cv2
    import numpy as np

    from services.vdoprocessing import color_match

    cap = cv2.VideoCapture(video_path)
    frame = None
    try:
        while True:
            ok, this = cap.read()
            if not ok:
                break
            frame = this
    finally:
        cap.release()
    if frame is None:
        raise RuntimeError(f"No frames in {video_path} to chain the next segment from.")

    if tuning.COMFYUI_CHAIN_COLOR_MATCH:
        photo = _read_image(photo_path)
        if photo is not None:
            h, w = frame.shape[:2]
            target = color_match._lab_stats(color_match._crop_to_aspect(photo, w, h))
            frame = color_match.correct_frame(frame, color_match._lab_stats(frame), target)
        else:
            logger.warning("Chain colour match skipped: can't read %s", photo_path)

    ok, buffer = cv2.imencode(".png", frame)
    if not ok:
        raise RuntimeError(f"Could not encode the last frame of {video_path}.")
    np.asarray(buffer).tofile(output_png)  # handles a non-ASCII path
    return output_png


def _join_segments(segment_paths: list, output_path: str) -> str:
    """Joins the chained segments into output_path at COMFYUI_FPS (frames
    repeated when Wan generated at a lower COMFYUI_GEN_FPS). Every segment
    after the first opens on a re-render of the frame it started from - the
    segment before it already ended on that frame - so its first frame is
    dropped."""
    from services.tts.ttsengine import FFmpegManager

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    if len(segment_paths) == 1 and tuning.COMFYUI_GEN_FPS == tuning.COMFYUI_FPS:
        Path(segment_paths[0]).replace(output_path)
        return output_path

    parts, labels = [], []
    for i, _ in enumerate(segment_paths):
        first = 0 if i == 0 else 1
        parts.append(f"[{i}:v]trim=start_frame={first},setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(segment_paths)}:v=1:a=0[out]"

    command = [FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_log_args()]
    for path in segment_paths:
        command += ["-i", path]
    command += [
        "-filter_complex", graph, "-map", "[out]",
        "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "18", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-r", str(tuning.COMFYUI_FPS), output_path,
    ]
    result = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"Joining the chained segments failed: {result.stderr.strip()}")
    return output_path


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
                        *(
                            ["--reserve-vram", str(tuning.COMFYUI_RESERVE_VRAM_GB)]
                            if tuning.COMFYUI_RESERVE_VRAM_GB else []
                        ),
                    ],
                    cwd=str(self._SERVER_DIR),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    **popen_kwargs,
                )
                self._PIDFILE.write_text(str(ComfyUII2VClient._server_process.pid))
                self._touch_activity()
                self._start_idle_watchdog(ComfyUII2VClient._server_process.pid)

        _ServerLogReporter("ComfyUI").show("starting server")
        deadline = time.monotonic() + tuning.COMFYUI_SERVER_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if self._is_server_up():
                logger.info("Bundled ComfyUI is up at %s.", self.base_url)
                return
            if (
                ComfyUII2VClient._server_process is not None
                and ComfyUII2VClient._server_process.poll() is not None
            ):
                for line in self._log_lines_tail(15):
                    tracker.note(f"[ComfyUI] {line}")
                raise RuntimeError(
                    "Bundled ComfyUI subprocess exited while starting up — "
                    f"see {self._SERVER_DIR / 'comfyui_server.log'} for details."
                )
            time.sleep(1.0)

        raise RuntimeError(
            f"Bundled ComfyUI did not become healthy within "
            f"{tuning.COMFYUI_SERVER_START_TIMEOUT_SECONDS:.0f}s of starting."
        )

    def _log_lines_tail(self, count: int) -> List[str]:
        tail = _ServerLogTail(self._SERVER_DIR / "comfyui_server.log")
        tail.offset = max(0, tail.offset - 8192)
        return tail.poll()[-count:]

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
        segments: int = 1,
        camera_pose: str = "Static",
    ) -> Dict[str, Any]:
        """The template graph, filled in. With segments > 1 it is extended in
        place (sequential extension, unrolled): each extra segment takes the
        previous segment's decoded LAST frame as its start image, samples and
        decodes `length` more frames, drops its own first frame (a copy of
        that start frame), and all segments are batched together before
        CreateVideo - one graph, so the model stays loaded throughout."""
        if _chains_only() and segments > 1:
            raise ValueError(f"{tuning.COMFYUI_MODEL} segments are chained, never unrolled into one graph.")
        if _is_a14b():
            graph = _a14b_template()
            graph["3"]["inputs"]["noise_seed"] = uuid.uuid4().int & 0xFFFFFFFFFFFF
        elif tuning.COMFYUI_MODEL == "fun_camera":
            graph = _fun_camera_template()
            graph["3"]["inputs"]["seed"] = uuid.uuid4().int & 0xFFFFFFFFFFFF
            graph["camera"]["inputs"]["camera_pose"] = camera_pose
            graph["camera"]["inputs"]["length"] = length
        else:
            graph = copy.deepcopy(_WORKFLOW_TEMPLATE)
            graph["3"]["inputs"]["seed"] = uuid.uuid4().int & 0xFFFFFFFFFFFF
        graph["56"]["inputs"]["image"] = uploaded_image_name
        if tuning.COMFYUI_MODEL != "fun_camera":  # there it comes from the camera node
            graph["55"]["inputs"]["length"] = length
        graph["6"]["inputs"]["text"] = prompt_text
        graph["58"]["inputs"]["filename_prefix"] = filename_prefix

        parts = [["8", 0]]
        previous_decode = "8"
        for k in range(1, segments):
            graph[f"ext{k}_last"] = {
                "inputs": {"image": [previous_decode, 0], "batch_index": -1, "length": 1},
                "class_type": "ImageFromBatch",
            }
            latent = copy.deepcopy(graph["55"])
            latent["inputs"]["start_image"] = [f"ext{k}_last", 0]
            graph[f"ext{k}_latent"] = latent
            sampler = copy.deepcopy(graph["3"])
            sampler["inputs"]["latent_image"] = [f"ext{k}_latent", 0]
            sampler["inputs"]["seed"] = uuid.uuid4().int & 0xFFFFFFFFFFFF
            graph[f"ext{k}_sample"] = sampler
            decode = copy.deepcopy(graph["8"])
            decode["inputs"]["samples"] = [f"ext{k}_sample", 0]
            graph[f"ext{k}_decode"] = decode
            graph[f"ext{k}_trim"] = {
                "inputs": {"image": [f"ext{k}_decode", 0], "batch_index": 1, "length": 4096},
                "class_type": "ImageFromBatch",
            }
            parts.append([f"ext{k}_trim", 0])
            previous_decode = f"ext{k}_decode"
        if segments > 1:
            graph["ext_batch"] = {
                "inputs": {f"images.image{i}": part for i, part in enumerate(parts)},
                "class_type": "BatchImagesNode",
            }
            graph["57"]["inputs"]["images"] = ["ext_batch", 0]
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

    def _wait_for_result(
        self,
        client: httpx.Client,
        prompt_id: str,
        output_node: str = None,
        timeout: float = None,
        log_tail: Optional[_ServerLogTail] = None,
        label: str = "Wan",
    ) -> Dict[str, Any]:
        output_node = output_node or _SAVE_VIDEO_NODE_ID
        timeout = timeout or tuning.COMFYUI_GENERATION_TIMEOUT_SECONDS
        log_tail = log_tail or _ServerLogTail(self._SERVER_DIR / "comfyui_server.log")
        reporter = _ServerLogReporter(label)
        reporter.show("queued")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            reporter.report(log_tail.poll())
            try:
                response = client.get(f"{self.base_url}/history/{prompt_id}", timeout=30.0)
                response.raise_for_status()
            except httpx.TransportError as exc:
                # A generation can take several minutes of real GPU work
                # (hundreds of 2s polls on the same pooled keep-alive
                # connection) — observed in the wild as a `ReadError:
                # [WinError 10054] An existing connection was forcibly
                # closed by the remote host` roughly 10 minutes in, well
                # before the job itself was actually done. httpx's own
                # connection pool doesn't retry a read failure on a stale
                # reused connection (only connect-phase failures), so
                # without this the whole ~10 minutes of already-completed
                # GPU work gets thrown away and the clip falls back to the
                # much slower local generator over what's really just one
                # transient dropped connection. Retrying opens a fresh
                # connection and keeps waiting on the SAME prompt_id — the
                # generation itself is unaffected, ComfyUI keeps running
                # server-side regardless of whether anyone's polling it.
                logger.warning(
                    "Transient connection error polling ComfyUI for prompt %s "
                    "(%s: %s) — retrying.",
                    prompt_id, type(exc).__name__, exc,
                )
                time.sleep(self._POLL_INTERVAL_SECONDS)
                continue
            history = response.json()
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error" or any(
                    m[0] == "execution_error" for m in status.get("messages", [])
                ):
                    reporter.report(log_tail.poll())
                    raise RuntimeError(
                        f"ComfyUI execution failed for prompt {prompt_id}: "
                        f"{status.get('messages')}"
                    )
                outputs = entry.get("outputs", {})
                if output_node in outputs:
                    return outputs[output_node]
            time.sleep(self._POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"ComfyUI generation for prompt {prompt_id} did not finish within "
            f"{timeout:.0f}s."
        )

    def run_image_graph(
        self,
        build_graph,
        image_path: str,
        output_node: str,
        output_path: str,
        timeout: float = None,
    ) -> str:
        """Uploads image_path, runs build_graph(uploaded_name) and saves the
        first image output_node produced to output_path. Raises on failure."""
        self._ensure_server_running()
        with httpx.Client() as client:
            graph = build_graph(self._upload_image(client, image_path))
            log_tail = _ServerLogTail(self._SERVER_DIR / "comfyui_server.log")
            prompt_id = self._submit(client, graph)
            outputs = self._wait_for_result(
                client, prompt_id, output_node, timeout, log_tail, f"Upscale {Path(image_path).name}"
            )
            self._touch_activity()
            images = outputs.get("images")
            if not images:
                raise RuntimeError(f"ComfyUI job {prompt_id} produced no image output.")
            self._download_video(client, images[0], output_path)
        return output_path

    def free_memory(self) -> None:
        """Unloads every model ComfyUI holds, so the next job starts with
        an empty GPU. Best-effort."""
        if not self._is_server_up():
            return
        try:
            with httpx.Client() as client:
                client.post(
                    f"{self.base_url}/free",
                    json={"unload_models": True, "free_memory": True},
                    timeout=30.0,
                )
        except httpx.HTTPError as exc:
            logger.warning("Could not free ComfyUI memory (%s).", exc)

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
        (Wan2.2 image-to-video, tuning.COMFYUI_MODEL) and saves it to
        output_path. Raises on any failure (server unreachable, execution
        error, timeout) — callers should catch and fall back to
        local_pan_generator.generate_local_clip."""
        self._ensure_server_running()

        segments, length = _resolve_segments(duration_sec)
        prompt_text = _resolve_motion_prompt(camera_pan_hint)
        camera_pose = _resolve_camera_pose(camera_pan_hint)
        cropped = f"{output_path}.input.png"
        image_path = _edge_cropped(image_path, cropped)
        try:
            self._generate(image_path, output_path, segments, length, prompt_text, camera_pose)
        finally:
            Path(cropped).unlink(missing_ok=True)
        logger.info("ComfyUI I2V clip saved to %s", output_path)
        return output_path

    def _generate(self, image_path, output_path, segments, length, prompt_text, camera_pose) -> None:
        with httpx.Client() as client:
            if segments > 1 and (tuning.COMFYUI_CHAIN_LAST_FRAME or _chains_only()):
                self._generate_chained(
                    client, image_path, output_path, segments, length, prompt_text, camera_pose
                )
            else:
                graph = self._build_graph(
                    self._upload_image(client, image_path), prompt_text, length,
                    f"attraction/{uuid.uuid4().hex[:8]}", segments, camera_pose,
                )
                logger.info(
                    "ComfyUI I2V: one graph, %d segment(s) x %d frames, prompt=%r",
                    segments, length, prompt_text,
                )
                if tuning.COMFYUI_GEN_FPS == tuning.COMFYUI_FPS:
                    self._run_segment(client, graph, output_path)
                else:
                    raw = f"{output_path}.gen.mp4"
                    try:
                        _join_segments([self._run_segment(client, graph, raw)], output_path)
                    finally:
                        Path(raw).unlink(missing_ok=True)

    def _run_segment(
        self, client: httpx.Client, graph: Dict[str, Any], output_path: str, label: str = "Wan",
    ) -> str:
        """Submits one graph, waits for it, and downloads the video it made."""
        log_tail = _ServerLogTail(self._SERVER_DIR / "comfyui_server.log")
        prompt_id = self._submit(client, graph)
        video_outputs = self._wait_for_result(client, prompt_id, log_tail=log_tail, label=label)
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
        return output_path

    def _generate_chained(
        self,
        client: httpx.Client,
        image_path: str,
        output_path: str,
        segments: int,
        length: int,
        prompt_text: str,
        camera_pose: str = "Static",
    ) -> str:
        """Last-frame chaining: one ComfyUI job per segment, each started from
        a PNG of the previous segment last frame (colour-matched back to the
        photo first), the segments then joined with ffmpeg. See
        tuning.COMFYUI_CHAIN_LAST_FRAME for why this is the default over
        unrolling every segment into one graph."""
        work = Path(output_path).parent / f".chain_{uuid.uuid4().hex[:8]}"
        work.mkdir(parents=True, exist_ok=True)
        try:
            paths = []
            start_image = image_path
            for k in range(segments):
                graph = self._build_graph(
                    self._upload_image(client, start_image), prompt_text, length,
                    f"attraction/{uuid.uuid4().hex[:8]}", 1, camera_pose,
                )
                segment_path = str(work / f"seg{k}.mp4")
                logger.info(
                    "ComfyUI I2V: chained segment %d/%d (%d frames) from %s",
                    k + 1, segments, length, Path(start_image).name,
                )
                self._run_segment(client, graph, segment_path, f"Wan segment {k + 1}/{segments}")
                paths.append(segment_path)
                if k + 1 < segments:
                    start_image = _write_last_frame(
                        segment_path, image_path, str(work / f"frame{k}.png")
                    )
            return _join_segments(paths, output_path)
        finally:
            for leftover in work.glob("*"):
                leftover.unlink(missing_ok=True)
            work.rmdir()
