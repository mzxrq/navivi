import os
import subprocess
import cv2
import numpy as np
from PIL import Image

# Plain single-shot zoom-out + pan: starts at the normal (zoom=1.0-equivalent)
# framing and zooms out while panning to reveal the AI-outpainted wider
# canvas. No multi-shot cuts, no crossfades, no color grade/vignette/grain/
# letterbox — just one continuous eased motion.

SRC_IMAGE = "kyoushieki.jpg"
OUTPAINT_IMAGE = "output_videos/outpainted.png"
OUT_VIDEO = "output_videos/zoom_out_pan.mp4"
OUT_W, OUT_H = 1280, 720
FPS = 30
DURATION_SEC = 6.0

ZOOM_END = 1.0        # 1.0 = fully zoomed out to the wide canvas's own contain-fit
PAN_DX_FRAC = 0.18    # horizontal drift over the shot, as a fraction of the wide canvas's fit width
USE_FOCUS = True      # start centered on the auto-detected subject rather than the image center


def ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * np.cos(np.pi * t)


def find_focus_point(gray: np.ndarray) -> tuple:
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    energy = cv2.magnitude(gx, gy)
    energy = cv2.GaussianBlur(energy, (0, 0), 15)
    h, w = energy.shape
    ys, xs = np.mgrid[0:h, 0:w]
    total = energy.sum() + 1e-6
    cx = float((xs * energy).sum() / total)
    cy = float((ys * energy).sum() / total)
    cx = 0.5 * cx + 0.5 * (w / 2)
    cy = 0.5 * cy + 0.5 * (h / 2)
    return cx, cy


def contain_fit(sw: int, sh: int, out_aspect: float) -> tuple:
    if sw / sh > out_aspect:
        fit_h = sh
        fit_w = int(fit_h * out_aspect)
    else:
        fit_w = sw
        fit_h = int(fit_w / out_aspect)
    return fit_w, fit_h


def crop_rect(cx: float, cy: float, half_w: float, half_h: float, sw: int, sh: int) -> tuple:
    half_w = min(half_w, sw / 2)
    half_h = min(half_h, sh / 2)
    cx = min(max(cx, half_w), sw - half_w)
    cy = min(max(cy, half_h), sh - half_h)
    return int(cx - half_w), int(cy - half_h), int(cx + half_w), int(cy + half_h)


def get_wide_source() -> np.ndarray:
    if not os.path.exists(OUTPAINT_IMAGE):
        print("No outpainted canvas cached yet - generating one (SDXL mirror-seed outpaint)...")
        # outpaint_sd15.py (SD1.5 + ControlNet-inpaint) is available as a
        # lighter-VRAM alternative if this ever needs to run on a tighter
        # card, but its output quality is noticeably worse (oversaturated,
        # prone to hallucinating secondary objects) — this SDXL approach is
        # the better default whenever it fits, which it does at 8GB.
        from outpaint_pan import outpaint as run_outpaint
        run_outpaint(SRC_IMAGE)
    return np.array(Image.open(OUTPAINT_IMAGE).convert("RGB"))


def main():
    out_aspect = OUT_W / OUT_H

    base_src = np.array(Image.open(SRC_IMAGE).convert("RGB"))
    base_aspect = base_src.shape[1] / base_src.shape[0]

    wide_src = get_wide_source()
    sh, sw = wide_src.shape[:2]
    fit_w, fit_h = contain_fit(sw, sh, out_aspect)
    focus = find_focus_point(cv2.cvtColor(wide_src, cv2.COLOR_RGB2GRAY)) if USE_FOCUS else (sw / 2, sh / 2)

    # The outpaint canvas is the original photo resized to this same height
    # (sh) and then extended sideways, so the original photo's full width —
    # in the wide canvas's own pixel space — is exactly sh * base_aspect.
    # (Comparing base_fit_w, computed from the original's own resolution,
    # directly against fit_w here was the bug: those pixel counts live at
    # two different scales and aren't comparable.)
    orig_width_in_wide_space = sh * base_aspect
    zoom_start = orig_width_in_wide_space / fit_w  # matches the plain photo's normal zoom=1.0 framing
    pan_dx = PAN_DX_FRAC * fit_w

    num_frames = int(DURATION_SEC * FPS)
    raw_path = OUT_VIDEO + ".raw.mp4"
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    os.makedirs("output_videos", exist_ok=True)
    writer = cv2.VideoWriter(raw_path, fourcc, FPS, (OUT_W, OUT_H))

    for i in range(num_frames):
        t = ease_in_out(i / max(1, num_frames - 1))
        zoom = zoom_start + (ZOOM_END - zoom_start) * t
        cx, cy = focus[0] + pan_dx * t, focus[1]
        half_w, half_h = fit_w * zoom / 2, fit_h * zoom / 2
        x0, y0, x1, y1 = crop_rect(cx, cy, half_w, half_h, sw, sh)
        crop = wide_src[y0:y1, x0:x1]
        frame = cv2.resize(crop, (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)
        writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    writer.release()

    subprocess.run(
        ["ffmpeg", "-y", "-i", raw_path, "-c:v", "libx264", "-crf", "20",
         "-preset", "medium", "-pix_fmt", "yuv420p", OUT_VIDEO],
        check=True, capture_output=True,
    )
    os.remove(raw_path)
    print(f"Saved {num_frames} frames to {OUT_VIDEO}")


if __name__ == "__main__":
    main()
