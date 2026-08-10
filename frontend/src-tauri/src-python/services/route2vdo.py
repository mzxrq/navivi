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

    points, labels, popups = [], [], []
    for item in route_data:
        if isinstance(item, (list, tuple)):
            points.append([float(item[0]), float(item[1])])
            labels.append(None)
            popups.append(None)
        elif isinstance(item, dict):
            points.append([float(item["x"]), float(item["y"])])
            labels.append(item.get("label"))
            
            # Extract popup data if it exists
            if "freeze_seconds" in item or "popup_image" in item:
                popups.append({
                    "freeze_seconds": float(item.get("freeze_seconds", 2.0)),
                    "popup_image": item.get("popup_image"),
                    "triggered": False  # We use this to track if we already paused here
                })
            else:
                popups.append(None)
        else:
            raise ValueError(f"Unknown point format: {item}")

    return points, labels, popups, settings


def draw_landmark(img, x, y, label, radius=16, font=cv2.FONT_HERSHEY_SIMPLEX):
    """Pin-style marker with a label bubble."""
    # Draw the map pin
    cv2.circle(img, (x, y), radius, (255, 80, 0), -1, cv2.LINE_AA)
    cv2.circle(img, (x, y), radius + 3, (255, 255, 255), 2, cv2.LINE_AA)

    # Get text size (using thickness 1 to match the actual drawn text)
    (tw, th), _ = cv2.getTextSize(label, font, 0.6, 1)
    
    # Calculate background box dimensions
    pad = 5
    bx1, by1 = x + radius + 4, y - th - pad
    bx2, by2 = x + radius + 4 + tw + pad * 2, y + pad
    
    # Draw the background box (dark border, white fill)
    cv2.rectangle(img, (bx1 - 1, by1 - 1), (bx2 + 1, by2 + 1), (50, 50, 50), -1)
    cv2.rectangle(img, (bx1, by1), (bx2, by2), (255, 255, 255), -1)

    # Draw the text exactly ONCE with a thickness of 1 so it doesn't collapse
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
    popups: list = None, # type: ignore
    output_path: str = "route_animation.mp4",
    fps: int = 30,
    duration_seconds: float = 8.0,
    line_color: tuple = (0, 200, 255),
    line_thickness: int = 10,
    marker_color: tuple = (0, 0, 255),
    marker_radius: int = 18,
    res_sequence: list = None, # type: ignore
    res_duration_per_slice: float = 5.0,
    pause_seconds: float = 2.0
):
    # 1. Load the Big Picture Map
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {img_path}")

    h, w = img.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX
    
    # 2. Setup Video Writer
    tmp_avi = tempfile.mktemp(suffix=".avi")
    video = cv2.VideoWriter(tmp_avi, cv2.VideoWriter_fourcc(*"XVID"), fps, (w, h)) # type: ignore
    if not video.isOpened():
        raise RuntimeError("OpenCV VideoWriter failed.")

    # ==========================================
    # PHASE 1: BIG PICTURE ROUTE
    # ==========================================
    num_frames = max(10, int(duration_seconds * fps))
    
    named = [
        (int(points[i][0]), int(points[i][1]), labels[i])
        for i in range(len(points)) if _is_real_label(labels[i])
    ]
    
    # Empty background image without landmarks baked in
    base_img = img.copy()

    smooth_path = _get_exact_path(points, num_frames)
    path_history: list[tuple[int, int]] = []
    last_frame = base_img.copy()

    # Bundle the coordinates with their popup data so we can check distances
    active_popups = []
    if popups:
        for i in range(len(points)):
            if popups[i] is not None:
                active_popups.append({
                    "x": points[i][0],
                    "y": points[i][1],
                    "data": popups[i],
                    "label": labels[i]  # Include the label for the popup box
                })

    print(f"Rendering Phase 1: Big Picture ({duration_seconds}s)")
    for p in smooth_path:
        frame = base_img.copy()
        path_history.append((int(p[0]), int(p[1])))

        # 1. Draw the trailing line
        if len(path_history) > 1:
            pts_arr = np.array(path_history, dtype=np.int32)
            cv2.polylines(frame, [pts_arr], False, line_color, line_thickness, cv2.LINE_AA)

        # 2. Draw landmarks so they sit on top of the yellow line
        for x, y, lbl in named:
            draw_landmark(frame, x, y, lbl, radius=16, font=font)

        # 3. Draw the leading dot on top of everything
        cx_, cy_ = path_history[-1]
        cv2.circle(frame, (cx_, cy_), marker_radius, marker_color, -1, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), marker_radius + 4, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), marker_radius + 7, marker_color, 1, cv2.LINE_AA)

        # --- POPUP LOGIC ---
        for popup in active_popups:
            dist = np.hypot(p[0] - popup["x"], p[1] - popup["y"])
            if dist < 5.0 and not popup["data"]["triggered"]:
                popup["data"]["triggered"] = True  
                
                print(f"📸 Triggering popup at ({popup['x']}, {popup['y']}) for {popup['data']['freeze_seconds']}s")
                
                freeze_frame = frame.copy()
                img_url = popup["data"].get("popup_image")
                
                if img_url and os.path.exists(img_url):
                    pop_img = cv2.imread(img_url)
                    if pop_img is not None:
                        pop_img = cv2.resize(pop_img, (400, 300))
                        ph, pw = pop_img.shape[:2]
                        
                        # Define the total bounding box size (just image + border, no text)
                        border = 8
                        total_w = pw + (border * 2)
                        total_h = ph + (border * 2)
                        
                        # Calculate ideal placement (above and to the right of the dot)
                        box_x = int(popup["x"]) + 20
                        box_y = int(popup["y"]) - total_h - 20
                        
                        # STRICTLY CONSTRAIN the entire box to the screen dimensions
                        box_x = max(0, min(box_x, w - total_w))
                        box_y = max(0, min(box_y, h - total_h))
                        
                        # Draw the white background box with a subtle gray outline
                        cv2.rectangle(freeze_frame, (box_x, box_y), (box_x + total_w, box_y + total_h), (255, 255, 255), -1)
                        cv2.rectangle(freeze_frame, (box_x, box_y), (box_x + total_w, box_y + total_h), (100, 100, 100), 2)
                        
                        # Paste the resized popup image perfectly inside the border
                        paste_y = box_y + border
                        paste_x = box_x + border
                        freeze_frame[paste_y:paste_y+ph, paste_x:paste_x+pw] = pop_img
                
                # Write the freeze frame to the video repeatedly
                freeze_frames_count = int(popup["data"]["freeze_seconds"] * fps)
                for _ in range(freeze_frames_count):
                    video.write(freeze_frame)
        # ------------------------

        last_frame = frame
        video.write(frame)

    # ==========================================
    # PHASE 2: THE PAUSE
    # ==========================================
    pause_frames = int(pause_seconds * fps)
    print(f"Pausing for {pause_seconds}s")
    for _ in range(pause_frames):
        video.write(last_frame)

    # ==========================================
    # PHASE 3: RESIDENTIAL MAPS (LOOP THROUGH SLICES)
    # ==========================================
    if res_sequence:
        for i, res_data in enumerate(res_sequence):
            print(f" Rendering Residential Map {i+1}/{len(res_sequence)}")
            
            res_img = cv2.imread(res_data["img_path"])
            res_points = res_data["points"]
            res_labels = res_data["labels"]
            
            if res_img is not None:
                if res_img.shape[:2] != (h, w):
                    res_img = cv2.resize(res_img, (w, h))
                    
                res_base = res_img.copy()
                
                # Prepare labels but don't draw them yet
                res_named = [
                    (int(res_points[j][0]), int(res_points[j][1]), res_labels[j])
                    for j in range(len(res_points)) if _is_real_label(res_labels[j])
                ]

                # Animate this specific slice
                res_frames = max(10, int(res_duration_per_slice * fps))
                res_smooth_path = _get_exact_path(res_points, res_frames)
                res_history: list[tuple[int, int]] = []

                for p in res_smooth_path:
                    frame = res_base.copy()
                    res_history.append((int(p[0]), int(p[1])))

                    # 1. Draw Polyline
                    if len(res_history) > 1:
                        pts_arr = np.array(res_history, dtype=np.int32)
                        cv2.polylines(frame, [pts_arr], False, line_color, line_thickness, cv2.LINE_AA)

                    # 2. Draw residential landmarks on top of the line
                    for x, y, lbl in res_named:
                        draw_landmark(frame, x, y, lbl, radius=16, font=font)

                    # 3. Draw leading dot
                    cx_, cy_ = res_history[-1]
                    cv2.circle(frame, (cx_, cy_), marker_radius, marker_color, -1, cv2.LINE_AA)
                    cv2.circle(frame, (cx_, cy_), marker_radius + 4, (255, 255, 255), 2, cv2.LINE_AA)
                    cv2.circle(frame, (cx_, cy_), marker_radius + 7, marker_color, 1, cv2.LINE_AA)

                    video.write(frame)
                    last_frame = frame
                    
                # Small pause before jumping to the next map slice
                for _ in range(fps):
                    video.write(last_frame)

    video.release()
    print(" Frames written ✓")

    output_path = str(output_path)
    if output_path.lower().endswith(".mp4") and reencode_to_h264(tmp_avi, output_path):
        os.remove(tmp_avi)
        total_dur = duration_seconds + pause_seconds + (len(res_sequence) * res_duration_per_slice if res_sequence else 0)
        print(f"Saved Final Video → '{output_path}' ({total_dur}s total, H.264)")
    else:
        avi_out = str(Path(output_path).with_suffix(".avi"))
        os.rename(tmp_avi, avi_out)
        print(f"⚠️  ffmpeg not found — saved as AVI → '{avi_out}'")

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
    
    # --- NEW ARGUMENTS FOR PHASE 3 ---
    parser.add_argument("--res-map", default=None, help="Path to the residential map image")
    parser.add_argument("--res-route", default=None, help="Path to the residential JSON route")
    parser.add_argument("--res-duration", type=float, default=12.0, help="Duration for the residential animation")
    parser.add_argument("--pause", type=float, default=2.0, help="Pause seconds between maps")
    
    args = parser.parse_args()

    # Load Phase 1 data
    points, labels, popups, settings = load_route(args.route)
    
    # Load Phase 3 data and structure it into a sequence
    res_sequence = None
    if args.res_route and args.res_map:
        res_points, res_labels, _, _ = load_route(args.res_route)
        res_sequence = [
            {
                "img_path": args.res_map,
                "points": res_points,
                "labels": res_labels
            }
        ]

    render_route_animation(
        img_path=args.map,
        points=points,
        labels=labels,
        popups=popups,
        output_path=args.output,
        fps=args.fps or settings.get("fps", 30),
        duration_seconds=args.duration or settings.get("duration_seconds", 8),
        line_color=tuple(settings.get("line_color", [0, 200, 255])),
        line_thickness=args.thickness or settings.get("line_thickness", 10),
        marker_color=tuple(settings.get("marker_color", [0, 0, 255])),
        marker_radius=args.radius or settings.get("marker_radius", 18),
        res_sequence=res_sequence, # type: ignore
        res_duration_per_slice=args.res_duration,
        pause_seconds=args.pause
    )

if __name__ == "__main__":
    main()