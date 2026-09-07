import os
import cv2
import numpy as np
from PIL import Image

# Reliable camera-pan video: slides a crop window across the source photo and
# encodes the frames to video. No diffusion model involved, so there is no
# hallucination/instability risk — it only reveals real pixels already present
# in the source image. Guaranteed to work on any hardware.

SRC_IMAGE = "narapark.jpg"
OUT_VIDEO = "output_videos/classic_pan.mp4"
OUT_W, OUT_H = 1280, 720     # output video resolution
DURATION_SEC = 4.0
FPS = 30
EASE = True                  # ease-in/ease-out instead of linear pan


def ease_in_out(t: float) -> float:
    return 0.5 - 0.5 * np.cos(np.pi * t)


def main():
    img = Image.open(SRC_IMAGE).convert("RGB")
    src = np.array(img)  # H, W, 3 (RGB)
    sh, sw = src.shape[:2]

    out_aspect = OUT_W / OUT_H
    ZOOM = 0.75  # window covers this fraction of the largest crop that still fits

    # "Contain" fit: the largest window with out_aspect that fits inside the source.
    if sw / sh > out_aspect:
        fit_h = sh
        fit_w = int(fit_h * out_aspect)
    else:
        fit_w = sw
        fit_h = int(fit_w / out_aspect)

    # Shrink by ZOOM so the window is smaller than the source, leaving room to pan.
    win_w = max(1, int(fit_w * ZOOM))
    win_h = max(1, int(fit_h * ZOOM))

    max_x = sw - win_w   # how far the window can travel horizontally
    max_y = sh - win_h
    assert max_x > 0 or max_y > 0, "no room to pan — lower ZOOM"

    num_frames = int(DURATION_SEC * FPS)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    os.makedirs("output_videos", exist_ok=True)
    writer = cv2.VideoWriter(OUT_VIDEO, fourcc, FPS, (OUT_W, OUT_H))

    for i in range(num_frames):
        t = i / max(1, num_frames - 1)
        if EASE:
            t = ease_in_out(t)

        x0 = int(max_x * t)          # pan left -> right
        y0 = max_y // 2              # vertically centered, no vertical drift

        crop = src[y0:y0 + win_h, x0:x0 + win_w]
        frame = cv2.resize(crop, (OUT_W, OUT_H), interpolation=cv2.INTER_LANCZOS4)
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        writer.write(frame_bgr)

    writer.release()
    print(f"Saved {num_frames} frames to {OUT_VIDEO}")


if __name__ == "__main__":
    main()
