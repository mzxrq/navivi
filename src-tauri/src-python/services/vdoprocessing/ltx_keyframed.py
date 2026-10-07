"""LTXV-13B camera moves between two real crops of the photo.

The first and last frames are crops of the photo itself, moved across it in the
preset's direction, and LTXV-13B 0.9.8 distilled (GGUF) fills the motion in
between. Both ends being real pixels leaves it no room to wander or invent.
After the chosen move comes a second, closer shot (ATTRACTION_SECOND_SHOT),
joined by a dissolve: one photo, several angles.
Sampling and decoding run as two ComfyUI jobs with a server restart between
them: in one job the text encoder, model and VAE together pushed RAM past 30 GB.
"""

import hashlib
import shutil
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2

from services import tuning
from services.logger.logger import setup_logger
from services.vdoprocessing.camera_pan import normalize_camera_pan
from services.vdoprocessing.clip_qc import read_image

logger = setup_logger("LtxKeyframed")


Rect = Tuple[int, int, int, int]  # x0, y0, width, height


def keyframe_rects(w: int, h: int, move: str) -> Tuple[Rect, Rect]:
    """(first, last) crop windows in a w x h photo, at the LTXV aspect. Pans
    slide a LTXV_CROP_WIDTH share of the widest window from edge to edge;
    zooms and the close-in shot scale about the middle."""
    aspect = tuning.LTXV_WIDTH / tuning.LTXV_HEIGHT
    full_w = min(w, round(h * aspect))

    def window(share: float, cx: float, cy: float) -> Rect:
        cw = max(2, round(full_w * share))
        ch = min(h, round(cw / aspect))
        x0 = int(min(max(round(cx - cw / 2), 0), w - cw))
        y0 = int(min(max(round(cy - ch / 2), 0), h - ch))
        return x0, y0, cw, ch

    s = tuning.LTXV_CROP_WIDTH
    mid_x, mid_y = w / 2, h / 2
    if move in ("panright", "panleft"):
        left, right = window(s, 0, mid_y), window(s, w, mid_y)
        return (left, right) if move == "panright" else (right, left)
    if move in ("panup", "pandown"):
        top, bottom = window(s, mid_x, 0), window(s, mid_x, h)
        return (bottom, top) if move == "panup" else (top, bottom)
    if move in ("closein", "closeout"):
        wide, tight = window(tuning.LTXV_CLOSE_WIDE, mid_x, mid_y), window(tuning.LTXV_CLOSE_TIGHT, mid_x, mid_y)
        return (wide, tight) if move == "closein" else (tight, wide)
    if move in tuning.LTXV_FREE_MOVES:
        whole = window(1.0, mid_x, mid_y)
        return whole, whole
    if move.startswith("walkfwd"):
        turn = {"walkfwdleft": -1, "walkfwdright": 1}.get(move, 0) * tuning.LTXV_WALK_TURN * full_w
        return (window(tuning.LTXV_CLOSE_WIDE, mid_x, mid_y),
                window(tuning.LTXV_WALK_TIGHT, mid_x + turn, mid_y))
    if move.startswith("closepan"):
        c = tuning.LTXV_CLOSE_WIDE
        dx = tuning.LTXV_CLOSE_PAN * full_w / 2
        dy = tuning.LTXV_CLOSE_PAN * round(full_w / aspect) / 2
        steps = {"closepanright": (-dx, 0, dx, 0), "closepanleft": (dx, 0, -dx, 0),
                 "closepanup": (0, dy, 0, -dy), "closepandown": (0, -dy, 0, dy)}
        ax, ay, bx, by = steps[move]
        return window(c, mid_x + ax, mid_y + ay), window(c, mid_x + bx, mid_y + by)
    # zoomin, zoomout and walkshort.
    wide, tight = window(tuning.LTXV_ZOOM_WIDE, mid_x, mid_y), window(tuning.LTXV_ZOOM_TIGHT, mid_x, mid_y)
    return (tight, wide) if move == "zoomout" else (wide, tight)


def crop_keyframes(photo_path: str, move: str, work_dir: Path) -> Tuple[str, str]:
    """(first, last) PNGs at LTXV_WIDTH x LTXV_HEIGHT for the move."""
    image = read_image(photo_path)
    if image is None:
        raise RuntimeError(f"Cannot read {photo_path}")
    h, w = image.shape[:2]
    work_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, (x0, y0, cw, ch) in zip(("first", "last"), keyframe_rects(w, h, move)):
        path = work_dir / f"{move}_{name}.png"
        frame = cv2.resize(image[y0:y0 + ch, x0:x0 + cw], (tuning.LTXV_WIDTH, tuning.LTXV_HEIGHT),
                           interpolation=cv2.INTER_AREA)
        cv2.imencode(".png", frame)[1].tofile(str(path))
        paths.append(str(path))
    return paths[0], paths[1]


def ensure_files() -> None:
    """Downloads any missing LTXV file (sha256-checked). Raises on failure."""
    from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient
    from services.vdoprocessing.videopipeline.upscale_step import _download

    for spec in tuning.LTXV_FILES.values():
        path = ComfyUII2VClient._SERVER_DIR / "models" / spec["folder"] / spec["file"]
        if path.is_file():
            continue
        part = path.with_name(path.name + ".part")
        path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Downloading %s", spec["file"])
        _download(spec["url"], part)
        digest = hashlib.sha256()
        with open(part, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                digest.update(chunk)
        if digest.hexdigest() != spec["sha256"]:
            part.unlink(missing_ok=True)
            raise RuntimeError(f"{spec['file']}: sha256 mismatch ({digest.hexdigest()})")
        part.replace(path)


def prompt_for(preset: str, seed: str = "", second: bool = False) -> str:
    """The second shot with ATTRACTION_SECOND_SHOT_STYLE "walk" gets a walk-inside
    prompt, picked per photo by `seed`."""
    import random

    walks = tuning.LTXV_WALK_PROMPTS.get(preset)
    if second and walks and tuning.ATTRACTION_SECOND_SHOT_STYLE == "walk":
        return random.Random(f"{seed}|{preset}|walk").choice(walks).format(place="the place")
    place = "the place" if preset in tuning.LTXV_FREE_MOVES else "the scene"
    return tuning.LTXV_PROMPTS[preset].format(place=place)


def sample_graph(start_name: str, end_name: Optional[str], prompt: str, seed: int, prefix: str) -> Dict:
    """Mirrors ComfyUI's ltxv_image_to_video template, loaders swapped for the
    GGUF model + separate VAE/T5, last frame pinned by LTXVAddGuide (none when
    end_name is None); stops at a saved latent."""
    files = tuning.LTXV_FILES
    graph = {
        "unet": {"class_type": "UnetLoaderGGUF", "inputs": {"unet_name": files["unet"]["file"]}},
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": files["vae"]["file"]}},
        "clip": {"class_type": "CLIPLoader", "inputs": {
            "clip_name": files["text_encoder"]["file"], "type": "ltxv", "device": "default"}},
        "pos": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["clip", 0]}},
        "neg": {"class_type": "CLIPTextEncode", "inputs": {"text": tuning.LTXV_NEGATIVE, "clip": ["clip", 0]}},
        "start": {"class_type": "LoadImage", "inputs": {"image": start_name}},
        "end": {"class_type": "LoadImage", "inputs": {"image": end_name}},
        "i2v": {"class_type": "LTXVImgToVideo", "inputs": {
            "positive": ["pos", 0], "negative": ["neg", 0], "vae": ["vae", 0], "image": ["start", 0],
            "width": tuning.LTXV_WIDTH, "height": tuning.LTXV_HEIGHT, "length": tuning.LTXV_FRAMES,
            "batch_size": 1, "strength": 1.0}},
        "guide": {"class_type": "LTXVAddGuide", "inputs": {
            "positive": ["i2v", 0], "negative": ["i2v", 1], "vae": ["vae", 0], "latent": ["i2v", 2],
            "image": ["end", 0], "frame_idx": -1, "strength": tuning.LTXV_GUIDE_STRENGTH}},
        "cond": {"class_type": "LTXVConditioning", "inputs": {
            "positive": ["guide", 0], "negative": ["guide", 1], "frame_rate": float(tuning.LTXV_FPS)}},
        "sigmas": {"class_type": "ManualSigmas", "inputs": {"sigmas": tuning.LTXV_SIGMAS}},
        "sampler": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "sample": {"class_type": "SamplerCustom", "inputs": {
            "model": ["unet", 0], "add_noise": True, "noise_seed": seed, "cfg": 1.0,
            "positive": ["cond", 0], "negative": ["cond", 1], "sampler": ["sampler", 0],
            "sigmas": ["sigmas", 0], "latent_image": ["guide", 2]}},
        "crop": {"class_type": "LTXVCropGuides", "inputs": {
            "positive": ["cond", 0], "negative": ["cond", 1], "latent": ["sample", 0]}},
        "lat": {"class_type": "SaveLatent", "inputs": {"samples": ["crop", 2], "filename_prefix": prefix}},
    }
    if end_name is None:
        for node in ("end", "guide", "crop"):
            del graph[node]
        graph["cond"]["inputs"].update(positive=["i2v", 0], negative=["i2v", 1])
        graph["sample"]["inputs"]["latent_image"] = ["i2v", 2]
        graph["lat"]["inputs"]["samples"] = ["sample", 0]
    return graph


def decode_graph(latent_name: str, prefix: str) -> Dict:
    return {
        "vae": {"class_type": "VAELoader", "inputs": {"vae_name": tuning.LTXV_FILES["vae"]["file"]}},
        "lat": {"class_type": "LoadLatent", "inputs": {"latent": latent_name}},
        "decode": {"class_type": "VAEDecodeTiled", "inputs": {
            "samples": ["lat", 0], "vae": ["vae", 0], "tile_size": 512, "overlap": 64,
            "temporal_size": tuning.LTXV_DECODE_TEMPORAL_SIZE,
            "temporal_overlap": tuning.LTXV_DECODE_TEMPORAL_OVERLAP}},
        "video": {"class_type": "CreateVideo", "inputs": {
            "images": ["decode", 0], "fps": float(tuning.LTXV_FPS), "bit_depth": "auto", "color_space": "sRGB"}},
        "58": {"class_type": "SaveVideo", "inputs": {
            "video": ["video", 0], "filename_prefix": prefix, "format": "auto", "format.codec": "auto"}},
    }


# The close move that goes the same way as each editor preset.
_SAME_WAY = {
    "panright": "closepanright", "panleft": "closepanleft", "panup": "closepanup",
    "pandown": "closepandown", "zoomin": "closein", "zoomout": "closeout",
    "walkfwd": "closein", "walkfwdleft": "closein", "walkfwdright": "closein", "walkshort": "closein",
}


def second_shot(preset: str, seed: str = "", photo_path: Optional[str] = None) -> Optional[str]:
    """ATTRACTION_SECOND_SHOT for this photo: a fixed move, or with "random" a
    pick from ATTRACTION_SECOND_SHOT_MOVES seeded by `seed` (the photo's
    content), never the first shot's direction. "auto" picks from the same
    list by what the photo shows (move_picker), random when it can't."""
    import random

    second = tuning.ATTRACTION_SECOND_SHOT
    if second in ("random", "auto"):
        # A walk-in first shot is followed by a close shot, not another walk.
        free_first = preset in tuning.LTXV_FREE_MOVES
        choices = [m for m in tuning.ATTRACTION_SECOND_SHOT_MOVES
                   if m != _SAME_WAY.get(preset) and m in tuning.LTXV_PROMPTS
                   and not (free_first and m in tuning.LTXV_FREE_MOVES)]
        if second == "auto" and photo_path and choices:
            from services.vdoprocessing.move_picker import pick_for_photo

            picked = pick_for_photo(photo_path, choices, seed)
            if picked:
                return picked
        return random.Random(f"{seed}|{preset}").choice(choices) if choices else None
    return second if second and second != preset and second in tuning.LTXV_PROMPTS else None


def source_size(photo_path: str) -> Tuple[int, int]:
    """(w, h) of the photo before upscale_step enlarged it (looked up in its
    upscaled/map.json), turned to the upscaled photo's orientation."""
    import json

    from PIL import Image

    path = Path(photo_path)
    original = path
    try:
        mapping = json.loads((path.parent / "map.json").read_text(encoding="utf-8"))
        original = next((Path(s) for s, u in mapping.items() if Path(u).name == path.name and Path(s).exists()), path)
    except (OSError, ValueError):
        pass
    with Image.open(path) as up, Image.open(original) as src:
        (uw, uh), (sw, sh) = up.size, src.size
    return (sh, sw) if (uw > uh) != (sw > sh) and sw != sh else (sw, sh)


def crop_source_px(photo_path: str, share: float) -> float:
    """Original-photo pixels across a crop of `share` of the widest window."""
    w, h = source_size(photo_path)
    return share * min(w, h * tuning.LTXV_WIDTH / tuning.LTXV_HEIGHT)


def close_crop_source_px(photo_path: str) -> float:
    """Original-photo pixels across the second shot's close crop."""
    return crop_source_px(photo_path, tuning.LTXV_CLOSE_WIDE)


def sharp_enough_preset(preset: str, photo_path: str) -> str:
    """A pinned walk on a photo too small for its tight crop becomes a zoom."""
    if not preset.startswith("walkfwd"):
        return preset
    try:
        px = crop_source_px(photo_path, tuning.LTXV_WALK_TIGHT)
    except OSError:
        return preset
    if px < tuning.ATTRACTION_SECOND_SHOT_MIN_SOURCE_PX:
        logger.info("LTXV %s on %s would be only %.0f px of the original - %s instead.",
                    preset, Path(photo_path).name, px, tuning.LTXV_SMALL_PHOTO_WALK_FALLBACK)
        return tuning.LTXV_SMALL_PHOTO_WALK_FALLBACK
    return preset


def shot_list(preset: str, seed: str = "", photo_path: Optional[str] = None) -> List[str]:
    """The chosen move, then the second shot - unless the photo is too small
    for a close crop to stay sharp."""
    if tuning.ATTRACTION_SECOND_SHOT and photo_path:
        try:
            px = close_crop_source_px(photo_path)
        except OSError:
            px = None
        if px is not None and px < tuning.ATTRACTION_SECOND_SHOT_MIN_SOURCE_PX:
            logger.info("No second shot for %s: its close crop is only %.0f px of the original photo.",
                        Path(photo_path).name, px)
            return [preset]
    second = second_shot(preset, seed, photo_path)
    return [preset, second] if second else [preset]


def _photo_seed(photo_path: str) -> str:
    digest = hashlib.sha1()
    with open(photo_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_shot(photo_path: str, move: str, output_path: str, work: Path, prompt: Optional[str] = None) -> str:
    """One LTXV clip (LTXV_FRAMES at LTXV_FPS) of `move` between its two crops,
    colour-matched to its own first crop. Raises on any failure."""
    import httpx

    from services.gpu_cooldown import wait_for_gpu_cooldown
    from services.vdoprocessing.color_match import match_clip_to_photo
    from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

    from services.vdoprocessing.local_pan_generator import release_models

    release_models()
    tuning.ensure_free_ram("LTXV clip", min_free_gb=tuning.LTXV_MIN_FREE_RAM_GB, relief=ComfyUII2VClient.stop_server)
    first, last = crop_keyframes(photo_path, move, work)
    prefix = f"attraction_ltx/{uuid.uuid4().hex[:8]}"
    client = ComfyUII2VClient()
    copied: Optional[Path] = None
    try:
        wait_for_gpu_cooldown(f"LTXV {move} for {Path(photo_path).name}")
        client._ensure_server_running()
        with httpx.Client() as http:
            graph = sample_graph(
                client._upload_image(http, first),
                None if move in tuning.LTXV_FREE_MOVES else client._upload_image(http, last),
                prompt or prompt_for(move), uuid.uuid4().int & 0xFFFFFFFF, prefix,
            )
            prompt_id = client._submit(http, graph)
            info = client._wait_for_result(http, prompt_id, output_node="lat", label=f"LTXV {move}")["latents"][0]
            saved = ComfyUII2VClient._SERVER_DIR / "output" / info.get("subfolder", "") / info["filename"]
            copied = ComfyUII2VClient._SERVER_DIR / "input" / info["filename"]
            shutil.copy2(saved, copied)
            saved.unlink(missing_ok=True)
            # A fresh server for the decode: /free alone left the sampling RAM in use.
            ComfyUII2VClient.stop_server()
            time.sleep(3)
            client._ensure_server_running()
            client._run_segment(http, decode_graph(info["filename"], prefix), output_path, label=f"LTXV {move} decode")
        match_clip_to_photo(output_path, first)
        logger.info("LTXV %s shot for %s -> %s", move, photo_path, output_path)
        return output_path
    finally:
        if copied is not None:
            copied.unlink(missing_ok=True)


def crossfade(paths: List[str], output_path: str) -> str:
    """Joins the shots with LTXV_CROSSFADE_SECONDS dissolves."""
    import subprocess

    from services.tts.ttsengine import FFmpegManager

    if len(paths) == 1:
        shutil.copy2(paths[0], output_path)
        return output_path
    fade = tuning.LTXV_CROSSFADE_SECONDS
    norm = f"fps={tuning.LTXV_FPS},scale={tuning.LTXV_WIDTH}:{tuning.LTXV_HEIGHT},setsar=1,format=yuv420p"
    chains = [f"[{i}:v]{norm}[s{i}]" for i in range(len(paths))]
    prev, offset = "s0", 0.0
    for i in range(1, len(paths)):
        offset += FFmpegManager.get_media_duration(paths[i - 1]) - fade
        out = f"x{i}"
        chains.append(f"[{prev}][s{i}]xfade=transition=fade:duration={fade}:offset={offset:.3f}[{out}]")
        prev = out
    cmd = [FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_log_args()]
    for path in paths:
        cmd += ["-i", path]
    cmd += ["-filter_complex", ";".join(chains), "-map", f"[{prev}]", "-c:v", "libx264",
            *tuning.ffmpeg_thread_args(), "-crf", "17", "-preset", "fast", "-pix_fmt", "yuv420p", output_path]
    result = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(f"Joining LTXV shots failed: {result.stderr.strip()}")
    return output_path


def pinned_preset(preset: str) -> str:
    """The editor's move, with a free walk swapped for LTXV_FREE_MOVE_FALLBACK."""
    fallback = tuning.LTXV_FREE_MOVE_FALLBACK
    if preset in tuning.LTXV_FREE_MOVES and fallback:
        logger.info("LTXV %s rendered as pinned %s.", preset, fallback)
        return fallback
    return preset


def generate_ltx_move(photo_path: str, output_path: str, camera_pan_hint) -> str:
    """The chosen move, then the second shot, dissolved together. A failed
    second shot leaves the first alone; a failed first raises."""
    preset = sharp_enough_preset(pinned_preset(normalize_camera_pan(camera_pan_hint)), photo_path)
    if preset not in tuning.LTXV_PROMPTS:
        raise ValueError(f"No LTXV recipe for preset {preset!r}")
    ensure_files()
    work = Path(output_path).parent / f".ltx_{uuid.uuid4().hex[:8]}"
    work.mkdir(parents=True, exist_ok=True)
    try:
        shots = []
        seed = _photo_seed(photo_path)
        for i, move in enumerate(shot_list(preset, seed, photo_path)):
            path = str(work / f"shot{i}.mp4")
            try:
                shots.append(render_shot(photo_path, move, path, work, prompt_for(move, seed, second=i > 0)))
            except Exception as exc:
                if i == 0:
                    raise
                logger.warning("LTXV %s shot failed (%s: %s) - keeping the first shot only.",
                               move, type(exc).__name__, exc)
        return crossfade(shots, output_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
