"""
route2vdo.py
---------------------------------------------------------------------------
Pixel-space route -> animated MP4 overlaid on a background map image.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
from scipy.interpolate import make_interp_spline

# Bundled ffmpeg binary, same layout pattern as GPSBABEL_BIN in gpsparser.py.
# Falls back to whatever "ffmpeg" resolves to on PATH if this isn't found,
# so this works whether or not ffmpeg is installed system-wide.
FFMPEG_BIN = Path(__file__).resolve().parent.parent / "bin" / "FFmpeg" / "bin" / "ffmpeg.exe"


def _resolve_ffmpeg() -> str | None:
    if FFMPEG_BIN.exists():
        return str(FFMPEG_BIN)
    return shutil.which("ffmpeg")


def _is_real_label(lbl) -> bool:
    """True for non-empty labels. Guards against NaN (a float, which is
    truthy in Python) getting drawn as the literal text 'nan'."""
    if lbl is None:
        return False
    if isinstance(lbl, float) and math.isnan(lbl):
        return False
    return str(lbl).strip() != ""


def load_route(json_path: str):
    """CLI/legacy support: load a pixel-space route.json."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        route_data, settings = data, {}
    else:
        route_data = data.get("route", data.get("points", []))
        settings = data.get("settings", {})

    points, labels = [], []
    for item in route_data:
        if isinstance(item, (list, tuple)):
            points.append([float(item[0]), float(item[1])])
            labels.append(None)
        elif isinstance(item, dict):
            points.append([float(item["x"]), float(item["y"])])
            labels.append(item.get("label"))
        else:
            raise ValueError(f"Unknown point format: {item}")

    return points, labels, settings


def draw_landmark(img, x, y, label, radius=16, font=cv2.FONT_HERSHEY_SIMPLEX):
    """Pin-style marker with a label bubble."""
    cv2.circle(img, (x, y), radius, (255, 80, 0), -1, cv2.LINE_AA)
    cv2.circle(img, (x, y), radius + 3, (255, 255, 255), 2, cv2.LINE_AA)

    (tw, th), _ = cv2.getTextSize(label, font, 0.6, 2)
    pad = 5
    bx1, by1 = x + radius + 4, y - th - pad
    bx2, by2 = x + radius + 4 + tw + pad * 2, y + pad
    cv2.rectangle(img, (bx1 - 1, by1 - 1), (bx2 + 1, by2 + 1), (50, 50, 50), -1)
    cv2.rectangle(img, (bx1, by1), (bx2, by2), (255, 255, 255), -1)

    cv2.putText(img, label, (bx1 + pad, y - 2), font, 0.6, (30, 30, 30), 2, cv2.LINE_AA)
    cv2.putText(img, label, (bx1 + pad, y - 2), font, 0.6, (30, 30, 30), 1, cv2.LINE_AA)


def reencode_to_h264(src: str, dst: str) -> bool:
    ffmpeg_cmd = _resolve_ffmpeg()
    if ffmpeg_cmd is None:
        return False
    try:
        r = subprocess.run(
            [ffmpeg_cmd, "-y", "-i", src,
             "-vcodec", "libx264", "-crf", "18",
             "-preset", "fast", "-pix_fmt", "yuv420p", dst],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return r.returncode == 0
    except FileNotFoundError:
        return False


def _get_exact_path(pts_list: list, frames: int) -> np.ndarray:
    """Straight-line (linear) interpolation through the exact input points,
    reparameterized by cumulative distance so speed stays constant."""
    filtered_pts = [pts_list[0]]
    for p in pts_list[1:]:
        if np.hypot(p[0] - filtered_pts[-1][0], p[1] - filtered_pts[-1][1]) > 0.1:
            filtered_pts.append(p)

    pts = np.array(filtered_pts, dtype=float)
    diffs = np.diff(pts, axis=0)
    dists = np.hypot(diffs[:, 0], diffs[:, 1])
    cum_dists = np.concatenate(([0], np.cumsum(dists)))
    total_dist = cum_dists[-1]

    t = cum_dists / total_dist if total_dist > 0 else np.linspace(0, 1, len(pts))
    t_fine = np.linspace(0, 1, frames)

    k = min(1, len(pts) - 1)  # linear
    sx = make_interp_spline(t, pts[:, 0], k=k)
    sy = make_interp_spline(t, pts[:, 1], k=k)
    return np.vstack([sx(t_fine), sy(t_fine)]).T


def render_route_animation(
    img_path: str,
    points: list,
    labels: list,
    output_path: str = "route_animation.mp4",
    fps: int = 30,
    duration_seconds: float = 8.0,
    line_color: tuple = (0, 200, 255),
    line_thickness: int = 10,
    marker_color: tuple = (0, 0, 255),
    marker_radius: int = 18,
):
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {img_path}")

    h, w = img.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    num_frames = max(10, int(duration_seconds * fps))

    print(f"  Points: {len(points)} (using all points, no simplification)")
    print(f"  Duration: {duration_seconds}s → {num_frames} frames @ {fps}fps")
    print(f"  Line thickness: {line_thickness},  marker radius: {marker_radius}")

    named = [
        (int(points[i][0]), int(points[i][1]), labels[i])
        for i in range(len(points))
        if _is_real_label(labels[i])
    ]
    print(f"  Named landmarks: {len(named)}")
    for lm in named:
        print(f"    '{lm[2]}' at ({lm[0]}, {lm[1]})")

    base_img = img.copy()
    for x, y, lbl in named:
        draw_landmark(base_img, x, y, lbl, radius=16, font=font)

    smooth_path = _get_exact_path(points, num_frames)

    tmp_avi = tempfile.mktemp(suffix=".avi")
    video = cv2.VideoWriter(tmp_avi, cv2.VideoWriter_fourcc(*"XVID"), fps, (w, h))  # type: ignore[attr-defined]
    if not video.isOpened():
        raise RuntimeError("OpenCV VideoWriter failed.")

    path_history: list[tuple[int, int]] = []

    for p in smooth_path:
        frame = base_img.copy()
        path_history.append((int(p[0]), int(p[1])))

        if len(path_history) > 1:
            pts_arr = np.array(path_history, dtype=np.int32)
            cv2.polylines(frame, [pts_arr], False, line_color, line_thickness, cv2.LINE_AA)

        cx_, cy_ = path_history[-1]
        cv2.circle(frame, (cx_, cy_), marker_radius, marker_color, -1, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), marker_radius + 4, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), marker_radius + 7, marker_color, 1, cv2.LINE_AA)

        video.write(frame)

    video.release()
    print("  Frames written ✓")

    output_path = str(output_path)
    if output_path.lower().endswith(".mp4") and reencode_to_h264(tmp_avi, output_path):
        os.remove(tmp_avi)
        print(f"✅  Saved → '{output_path}'  ({duration_seconds}s, H.264)")
    else:
        avi_out = str(Path(output_path).with_suffix(".avi"))
        os.rename(tmp_avi, avi_out)
        print(f"⚠️  ffmpeg not found at {FFMPEG_BIN} or on PATH — saved as AVI → '{avi_out}'")

    return output_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--output", default="route_animation.mp4")
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--thickness", type=int, default=None)
    parser.add_argument("--radius", type=int, default=None)
    args = parser.parse_args()

    points, labels, settings = load_route(args.route)

    render_route_animation(
        img_path=args.map,
        points=points,
        labels=labels,
        output_path=args.output,
        fps=args.fps or settings.get("fps", 30),
        duration_seconds=args.duration or settings.get("duration_seconds", 8),
        line_color=tuple(settings.get("line_color", [0, 200, 255])),
        line_thickness=args.thickness or settings.get("line_thickness", 10),
        marker_color=tuple(settings.get("marker_color", [0, 0, 255])),
        marker_radius=args.radius or settings.get("marker_radius", 18),
    )


if __name__ == "__main__":
    main()