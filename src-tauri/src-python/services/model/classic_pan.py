import os
import cv2
import numpy as np
from PIL import Image

# Reliable camera-pan video: slides a crop window across the source photo and
# encodes the frames to video. No diffusion model involved, so there is no
# hallucination/instability risk — it only reveals real pixels already present
# in the source image. Guaranteed to work on any hardware.

SRC_IMAGE = "kyoushieki.jpg"
OUT_VIDEO = "output_videos/classic_pan_kyoushieki.mp4"
OUT_W, OUT_H = 1280, 720     # output video resolution
DURATION_SEC = 7.0            # was 4.0 — same travel distance now reads as a slower, longer pan
FPS = 30
EASE = True                  # ease-in/ease-out instead of linear pan
# "auto" picks whichever axis has more travel room, which for a source whose
# proportions are far from the output aspect can pick a structurally-larger
# but compositionally-worse axis (e.g. a square photo panned vertically sky-
# to-ground instead of horizontally past the actual subject). Set "x" or "y"
# to force the axis that actually makes sense for a given photo.
PAN_AXIS_OVERRIDE = "x"
# Bias for the axis NOT being panned (0=top/left, 0.5=centered, 1=bottom/
# right) — lets you frame the subject instead of a pure geometric center.
CROSS_AXIS_BIAS = 0.65


def ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * np.cos(np.pi * t)


def main():
    img = Image.open(SRC_IMAGE).convert("RGB")
    src = np.array(img)  # H, W, 3 (RGB)
    sh, sw = src.shape[:2]

    out_aspect = OUT_W / OUT_H
    ZOOM = 0.6  # zoomed in a bit to leave real travel room for the pan

    # "Contain" fit: the largest window with out_aspect that fits inside the source.
    if sw / sh > out_aspect:
        fit_h = sh
        fit_w = int(fit_h * out_aspect)
    else:
        fit_w = sw
        fit_h = int(fit_w / out_aspect)

    # Shrink by ZOOM so the window is smaller than the source, leaving room to pan.
    # At ZOOM=1.0 the window is the full "contain" fit — whichever axis the
    # source is wider/taller than that fit is where the pan travel comes from.
    win_w = max(1, int(fit_w * ZOOM))
    win_h = max(1, int(fit_h * ZOOM))

    max_x = sw - win_w   # how far the window can travel horizontally
    max_y = sh - win_h   # how far the window can travel vertically
    # Pan along whichever axis actually has room; the other stays at
    # CROSS_AXIS_BIAS, unless PAN_AXIS_OVERRIDE forces a specific axis.
    if PAN_AXIS_OVERRIDE in ("x", "y"):
        pan_axis = PAN_AXIS_OVERRIDE
    else:
        pan_axis = "x" if max_x >= max_y else "y"
    if max_x <= 0 and max_y <= 0:
        print("No room to pan at ZOOM=1.0 — this photo exactly fills the frame; "
              "output will be a static shot. Lower ZOOM for real motion.")

    num_frames = int(DURATION_SEC * FPS)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    os.makedirs("output_videos", exist_ok=True)
    writer = cv2.VideoWriter(OUT_VIDEO, fourcc, FPS, (OUT_W, OUT_H))

    for i in range(num_frames):
        t = i / max(1, num_frames - 1)
        if EASE:
            t = ease_in_out(t)

        if pan_axis == "x":
            x0 = int(max_x * t)                    # pan left -> right
            y0 = int(max_y * CROSS_AXIS_BIAS)      # fixed vertical framing
        else:
            x0 = int(max_x * CROSS_AXIS_BIAS)      # fixed horizontal framing
            y0 = int(max_y * t)                    # pan top -> bottom

        crop = src[y0:y0 + win_h, x0:x0 + win_w]
        frame = cv2.resize(crop, (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        writer.write(frame_bgr)

    writer.release()
    print(f"Saved {num_frames} frames to {OUT_VIDEO}")


if __name__ == "__main__":
    main()
