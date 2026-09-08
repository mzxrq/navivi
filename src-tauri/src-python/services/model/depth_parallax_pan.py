import os
import cv2
import numpy as np
import torch
from PIL import Image
from transformers import pipeline

# Depth-based "2.5D" parallax pan: split the photo into near/mid/far layers
# using a monocular depth model (one-shot, deterministic — no per-frame
# generation, so none of the temporal-drift risk video diffusion had), then
# pan each layer at a different speed so foreground visibly separates from
# background as the camera moves. Falls back to plain content underneath
# each layer via classical inpainting, not AI generation.

SRC_IMAGE = "narapark.jpg"
OUT_VIDEO = "output_videos/depth_parallax_pan.mp4"
OUT_W, OUT_H = 1280, 720
DURATION_SEC = 6.0
FPS = 30
EASE = True

WORK_H = 900                    # working resolution for depth + compositing
NUM_LAYERS = 3                  # near, mid, far
LAYER_SPEEDS = [1.0, 0.55, 0.25]  # parallax multiplier per layer, near -> far
PAN_FRAC = 0.16                  # global pan distance as a fraction of working width
FEATHER_PX = 15                  # mask feather between layers


def ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * np.cos(np.pi * t)


# [Core] [Animation] Runs a monocular depth model once and returns a normalized 0-1 depth map (0=far, 1=near)
def estimate_depth(pil_img: Image.Image) -> np.ndarray:
    print("Loading depth model...")
    depth_pipe = pipeline(
        task="depth-estimation",
        model="depth-anything/Depth-Anything-V2-Small-hf",
        device=0 if torch.cuda.is_available() else -1,
    )
    print("Estimating depth...")
    result = depth_pipe(pil_img)
    depth = np.array(result["depth"], dtype=np.float32)
    depth = (depth - depth.min()) / max(1e-6, (depth.max() - depth.min()))
    del depth_pipe
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return depth  # 0 = far, 1 = near


def build_layers(rgb: np.ndarray, depth: np.ndarray, num_layers: int):
    """Returns a list of (inpainted_full_texture, feathered_mask) from
    nearest to farthest. Each texture is a complete plausible image (gaps
    filled via classical inpainting); each mask is where that layer's real
    content actually is."""
    h, w = depth.shape
    # [NOTE] [Animation] Bin edges from percentiles so each layer covers a similar amount of area.
    edges = np.quantile(depth, np.linspace(0, 1, num_layers + 1))
    layers = []
    for i in range(num_layers):
        lo, hi = edges[num_layers - 1 - i], edges[num_layers - i]  # near -> far
        if i == 0:
            mask = (depth >= lo).astype(np.uint8) * 255
        elif i == num_layers - 1:
            mask = (depth <= hi).astype(np.uint8) * 255
        else:
            mask = ((depth >= lo) & (depth <= hi)).astype(np.uint8) * 255

        # [NOTE] [Animation] Classical inpainting (not AI generation) fills each layer's
        # occluded areas so every layer is a complete texture that can be shifted
        # independently without exposing holes where another layer used to cover it.
        inpaint_mask = cv2.bitwise_not(mask)
        texture = cv2.inpaint(rgb, inpaint_mask, 15, cv2.INPAINT_TELEA)

        feathered = cv2.GaussianBlur(mask, (0, 0), FEATHER_PX).astype(np.float32) / 255.0
        layers.append((texture, feathered))
    return layers


def shift_image(img: np.ndarray, dx: float) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, 0]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]),
                           borderMode=cv2.BORDER_REPLICATE)


def shift_mask(mask: np.ndarray, dx: float) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, 0]])
    return cv2.warpAffine(mask, m, (mask.shape[1], mask.shape[0]),
                           borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def main():
    raw = Image.open(SRC_IMAGE).convert("RGB")
    src_aspect = raw.width / raw.height
    work_w = int(WORK_H * src_aspect)
    work_img = raw.resize((work_w, WORK_H))
    rgb = np.array(work_img)

    depth = estimate_depth(work_img)
    depth = cv2.resize(depth, (work_w, WORK_H))

    print("Building depth layers...")
    layers = build_layers(rgb, depth, NUM_LAYERS)

    pan_px = int(work_w * PAN_FRAC)
    # Extra margin so a shifted layer never exposes its own replicate-padded edge.
    margin = pan_px + FEATHER_PX * 2
    crop_w, crop_h = OUT_W, OUT_H
    out_aspect = OUT_W / OUT_H
    view_h = WORK_H - 2 * margin if WORK_H - 2 * margin > 0 else WORK_H
    view_w = int(view_h * out_aspect)

    num_frames = int(DURATION_SEC * FPS)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    os.makedirs("output_videos", exist_ok=True)
    writer = cv2.VideoWriter(OUT_VIDEO, fourcc, FPS, (OUT_W, OUT_H))

    print("Rendering frames...")
    for f in range(num_frames):
        t = f / max(1, num_frames - 1)
        if EASE:
            t = ease_in_out(t)
        global_dx = (t - 0.5) * 2 * pan_px  # sweep from -pan_px to +pan_px

        # [NOTE] [Animation] Composite back-to-front with per-layer speed: each layer shifts
        # by global_dx scaled by its own LAYER_SPEEDS multiplier, so near layers move more
        # than far ones — that differential creates the parallax depth illusion. Alpha-blends
        # (via each layer's feathered mask) over whatever the farther layers already drew.
        composite = None
        for i in range(NUM_LAYERS - 1, -1, -1):
            texture, mask = layers[i]
            dx = global_dx * LAYER_SPEEDS[i]
            shifted_tex = shift_image(texture, dx)
            shifted_mask = shift_mask(mask, dx)[..., None]
            if composite is None:
                composite = shifted_tex.astype(np.float32)
            else:
                composite = shifted_tex.astype(np.float32) * shifted_mask + composite * (1 - shifted_mask)

        composite = np.clip(composite, 0, 255).astype(np.uint8)

        cx0 = (work_w - view_w) // 2
        cy0 = margin
        crop = composite[cy0:cy0 + view_h, cx0:cx0 + view_w]
        frame = cv2.resize(crop, (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        writer.write(frame_bgr)

    writer.release()
    print(f"Saved {num_frames} frames to {OUT_VIDEO}")


if __name__ == "__main__":
    main()
