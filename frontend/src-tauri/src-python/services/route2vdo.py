"""
route2vdo.py
---------------------------------------------------------------------------
STAGE 5 of the pipeline: turns a pixel-space route (points already
projected onto a static map image) into an animated MP4 navigation video.

HIGH-LEVEL PROCESS (what this file actually does, top to bottom):

    1.  load_route()            -> reads route.json into (points, labels, popups, settings)
    2.  render_route_animation()  is the orchestrator. It writes frames into
        an OpenCV VideoWriter in four sequential PHASES:

            PHASE 1 - BIG PICTURE
                Animate a dot travelling along the full route on the main
                map image, drawing a trailing line + any landmark pins.
                Waypoint "popups" (photo cards) can freeze the animation
                briefly when the dot passes near them.

            PHASE 2 - PAUSE
                Hold on the final Phase-1 frame for a beat, so the cut
                into the residential maps doesn't feel abrupt.

            PHASE 3 - RESIDENTIAL MAPS
                Loop through zoomed-in "residential" map slices (e.g. from
                mapfetcher.generate_residential_map_series) and animate the
                dot through each one in turn.

            PHASE 4 - SUMMARY CARD (NEW)
                Freeze on the very last frame and fade in a rounded
                "distance / time spent" card in a corner, matching a
                Google-Maps-style trip-summary card. Held for a few
                seconds so it's readable, then the video ends.

    3.  reencode_to_h264()      -> OpenCV writes raw AVI (XVID); we then
        shell out to ffmpeg to produce a properly compressed, widely
        compatible H.264 MP4. If ffmpeg isn't available, we fall back to
        shipping the AVI so the pipeline never hard-fails on this step.

WHY TWO RENDERING LIBRARIES (OpenCV + PIL) ARE USED TOGETHER:
    OpenCV is fast at raw frame/video I/O and simple vector primitives
    (circles, lines, polylines) - it owns the main animation loop.
    PIL (Pillow) is used ONLY for the summary card, because it is the
    only one of the two that can do proper anti-aliased rounded
    rectangles and Unicode/TrueType text layout. The card is rendered
    ONCE on its own small canvas and then alpha-composited onto frames
    many times, rather than re-rendering text on every frame - see the
    comments on render_summary_card() for why that matters performance-
    wise.
---------------------------------------------------------------------------
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
from typing import Final

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.interpolate import make_interp_spline

# ---------------------------------------------------------------------
# Bundled ffmpeg binary, same layout pattern as GPSBABEL_BIN in
# gpsparser.py. Anchored to THIS file's location (not the process's
# current working directory) so it resolves correctly no matter where
# the Tauri sidecar process is launched from. Falls back to whatever
# "ffmpeg" resolves to on PATH if the bundled copy isn't found, so this
# still works in dev environments without the bundled binary.
# ---------------------------------------------------------------------
FFMPEG_BIN = Path(__file__).resolve().parent.parent / "bin" / "FFmpeg" / "bin" / "ffmpeg.exe"


def _resolve_ffmpeg() -> str | None:
    """Prefer the bundled ffmpeg; fall back to a system PATH install."""
    if FFMPEG_BIN.exists():
        return str(FFMPEG_BIN)
    return shutil.which("ffmpeg")


def _is_real_label(lbl) -> bool:
    """
    True for non-empty labels. Guards against NaN (a float, which is
    truthy in Python) getting drawn as the literal text 'nan' - a subtle
    bug that only shows up when a landmark label column has missing
    values, which pandas represents as float NaN rather than None.
    """
    if lbl is None:
        return False
    if isinstance(lbl, float) and math.isnan(lbl):
        return False
    return str(lbl).strip() != ""


# =======================================================================
# STEP 1: LOAD THE ROUTE
# =======================================================================
def load_route(json_path: str):
    """
    CLI/legacy support: load a pixel-space route.json.

    Accepts either a bare list of points, or an object with a
    "route"/"points" key plus a "settings" sub-object (fps, colors,
    etc.) so render defaults can be authored alongside the route data
    itself instead of always being passed on the command line.
    """
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
            # Plain [x, y] pair - no label/popup metadata.
            points.append([float(item[0]), float(item[1])])
            labels.append(None)
            popups.append(None)
        elif isinstance(item, dict):
            points.append([float(item["x"]), float(item["y"])])
            labels.append(item.get("label"))

            # A point only carries popup data if it explicitly opts in
            # via freeze_seconds/popup_image - everything else gets a
            # None placeholder so points/labels/popups all stay the
            # same length and index-aligned with each other.
            if "freeze_seconds" in item or "popup_image" in item:
                popups.append({
                    "freeze_seconds": float(item.get("freeze_seconds", 2.0)),
                    "popup_image": item.get("popup_image"),
                    "triggered": False,  # tracks whether we've already paused here
                })
            else:
                popups.append(None)
        else:
            raise ValueError(f"Unknown point format: {item}")

    return points, labels, popups, settings


# =======================================================================
# STEP 2: DRAWING PRIMITIVES USED DURING THE MAIN ANIMATION LOOP
# =======================================================================
def draw_landmark(img, x, y, label, radius=16, font=cv2.FONT_HERSHEY_SIMPLEX):
    """
    Pin-style marker with a text label bubble, drawn directly with
    OpenCV. This runs on every frame a landmark is visible on, so it
    stays intentionally cheap (a handful of circle/rectangle/text
    calls) rather than routed through PIL like the summary card is.
    """
    # The pin itself: solid dot + white ring outline.
    cv2.circle(img, (x, y), radius, (255, 80, 0), -1, cv2.LINE_AA)
    cv2.circle(img, (x, y), radius + 3, (255, 255, 255), 2, cv2.LINE_AA)

    # Measure text with thickness=1 so the box we draw actually matches
    # what gets rendered (mismatched thickness here is a common source
    # of clipped label boxes).
    (tw, th), _ = cv2.getTextSize(label, font, 0.6, 1)

    pad = 5
    bx1, by1 = x + radius + 4, y - th - pad
    bx2, by2 = x + radius + 4 + tw + pad * 2, y + pad

    # Dark 1px border behind a white fill gives the label bubble a
    # crisp edge against any map background color.
    cv2.rectangle(img, (bx1 - 1, by1 - 1), (bx2 + 1, by2 + 1), (50, 50, 50), -1)
    cv2.rectangle(img, (bx1, by1), (bx2, by2), (255, 255, 255), -1)

    cv2.putText(img, label, (bx1 + pad, y - 2), font, 0.6, (30, 30, 30), 1, cv2.LINE_AA)


# =======================================================================
# STEP 3: SUMMARY CARD (Phase 4 - new "distance / time spent" overlay)
# =======================================================================

# Ordered font search lists: first hit wins. Kept as small, well-known
# system-font names rather than a single hardcoded path, so the card
# still renders (just with a different-but-legible font) on machines
# that don't have the exact font installed, instead of crashing.
_FONT_CANDIDATES_BOLD: Final[list[str]] = [
    "seguisb.ttf", "segoeuib.ttf",                    # Windows
    "/System/Library/Fonts/SFNSDisplay-Bold.otf",      # macOS
    "DejaVuSans-Bold.ttf",                             # Linux / Pillow-bundled fallback
]
_FONT_CANDIDATES_REGULAR: Final[list[str]] = [
    "segoeui.ttf",
    "/System/Library/Fonts/SFNSDisplay.otf",
    "DejaVuSans.ttf",
]

# NOTE ON CJK LABELS (e.g. "歩く時間" / "距離" from the reference card):
# DejaVuSans has NO CJK glyph coverage and will render tofu boxes for
# Japanese text. If Japanese labels are required, bundle a CJK-capable
# font (e.g. Noto Sans JP) with the app and add its path to the front
# of the candidate lists above.


def _load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    """
    Try each candidate font in order; fall back to PIL's built-in
    bitmap font rather than raising, so a missing font degrades the
    card's *appearance* instead of breaking the whole render pipeline.
    """
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default() # type: ignore


def _draw_walking_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: tuple):
    """
    Vector walking-figure icon (head, torso, striding legs, swinging
    arm) built from primitive lines/ellipses - matches the reference
    card's pictogram without depending on an external icon asset file
    that could go missing at runtime in a packaged desktop app.
    """
    r = size // 6
    draw.ellipse([cx - r, cy - size // 2, cx + r, cy - size // 2 + 2 * r], fill=color)  # head
    torso_top = (cx, cy - size // 2 + 2 * r)
    torso_bottom = (cx - size // 8, cy)
    draw.line([torso_top, torso_bottom], fill=color, width=max(2, size // 12))  # torso
    draw.line([torso_bottom, (cx - size // 3, cy + size // 2)], fill=color, width=max(2, size // 12))       # back leg
    draw.line([torso_bottom, (cx + size // 4, cy + size // 2 - r // 2)], fill=color, width=max(2, size // 12))  # front leg
    draw.line([torso_top, (cx - size // 3, cy - size // 6)], fill=color, width=max(2, size // 14))           # arm


def _draw_ruler_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: tuple):
    """Vector ruler/distance icon: a diagonal bar with tick marks."""
    half = size // 2
    p1 = (cx - half, cy + half // 2)
    p2 = (cx + half, cy - half // 2)
    width = max(3, size // 10)
    draw.line([p1, p2], fill=color, width=width)
    for t in (0.25, 0.5, 0.75):
        tx = p1[0] + (p2[0] - p1[0]) * t
        ty = p1[1] + (p2[1] - p1[1]) * t
        draw.line([(tx - 4, ty - 6), (tx + 4, ty + 6)], fill=color, width=2)


def _format_duration_short(seconds: float) -> str:
    """'10 min', '1 hr 05 min', etc. - matches the reference card's terse style."""
    total_minutes = int(round(seconds / 60))
    hrs, mins = divmod(total_minutes, 60)
    return f"{hrs} hr {mins:02d} min" if hrs else f"{mins} min"


def render_summary_card(
    distance_km: float,
    duration_seconds: float,
    labels: tuple[str, str] = ("Time", "Distance"),
    card_size: tuple[int, int] = (460, 100),
) -> np.ndarray:
    """
    Renders the pill-shaped "distance / time spent" card ONCE onto its
    own small RGBA canvas, then returns it as a BGRA numpy array ready
    for alpha compositing onto video frames.

    WHY RENDER ONCE INSTEAD OF PER-FRAME:
    Text layout and font rasterization are the expensive part of this
    operation, not the alpha blend that happens later. The card's
    *content* doesn't change across the freeze phase (only its opacity
    during the fade-in does), so we hoist all the PIL drawing work out
    of the per-frame loop entirely and reuse this single result for
    every frame of Phase 4. This turns an O(frames * text-layout-cost)
    operation into O(text-layout-cost) + O(frames * cheap-blend-cost).
    """
    w, h = card_size

    # Supersample at 2x then downscale with Lanczos resampling - a
    # cheap anti-aliasing trick, since PIL's rounded_rectangle/ellipse
    # primitives are NOT anti-aliased natively at their target size.
    scale = 2
    canvas = Image.new("RGBA", (w * scale, h * scale), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    bg_color = (250, 250, 250, 235)   # near-white, slightly translucent pill
    text_color = (40, 40, 40, 255)
    icon_color = (80, 80, 80, 255)
    divider_color = (210, 210, 210, 255)

    radius = (h * scale) // 2
    draw.rounded_rectangle([0, 0, w * scale - 1, h * scale - 1], radius=radius, fill=bg_color)

    font_label = _load_font(_FONT_CANDIDATES_REGULAR, 15 * scale)
    font_value = _load_font(_FONT_CANDIDATES_BOLD, 24 * scale)

    icon_size = 44 * scale
    pad = 28 * scale

    # --- Left block: time spent ---
    icon_cx = pad + icon_size // 2
    icon_cy = h * scale // 2
    _draw_walking_icon(draw, icon_cx, icon_cy, icon_size, icon_color)

    text_x = pad + icon_size + 14 * scale
    duration_str = _format_duration_short(duration_seconds)
    draw.text((text_x, 22 * scale), labels[0], font=font_label, fill=text_color)
    draw.text((text_x, 44 * scale), duration_str, font=font_value, fill=text_color)

    # --- Vertical divider between the two stat blocks ---
    div_x = w * scale // 2
    draw.line([(div_x, 20 * scale), (div_x, h * scale - 20 * scale)], fill=divider_color, width=2 * scale)

    # --- Right block: distance ---
    icon_cx2 = div_x + 30 * scale + icon_size // 2
    _draw_ruler_icon(draw, icon_cx2, icon_cy, icon_size, icon_color)

    text_x2 = icon_cx2 + icon_size // 2 + 14 * scale
    # Sub-kilometer distances read as meters (e.g. "650 m"), matching
    # how the reference card would present a short walk.
    distance_str = f"{distance_km * 1000:.0f} m" if distance_km < 1 else f"{distance_km:.2f} km"
    draw.text((text_x2, 22 * scale), labels[1], font=font_label, fill=text_color)
    draw.text((text_x2, 44 * scale), distance_str, font=font_value, fill=text_color)

    canvas = canvas.resize((w, h), Image.LANCZOS)  # type: ignore # downsample = anti-alias

    # PIL works in RGBA; OpenCV frames are BGR. Swap channel order ONCE
    # here so composite_card_on_frame() can do a straight numpy blend
    # with no per-pixel channel logic in its hot loop.
    rgba = np.array(canvas)
    bgra = rgba[:, :, [2, 1, 0, 3]]
    return bgra


def composite_card_on_frame(
    frame: np.ndarray,
    card_bgra: np.ndarray,
    alpha: float,
    margin: int = 40,
    anchor: str = "bottom-right",
) -> np.ndarray:
    """
    Alpha-blends the pre-rendered card onto a COPY of `frame` at the
    given global opacity (0.0-1.0, driving the fade-in ramp) anchored
    to a corner of the frame.

    Only the card-sized sub-region of the frame is touched - this is
    O(card_area), not O(full_frame_area) - which is what keeps Phase 4
    cheap even though it runs once per freeze-phase frame.
    """
    out = frame.copy()
    h, w = out.shape[:2]
    ch, cw = card_bgra.shape[:2]

    # Safety net: if the card (plus its margins) is larger than the
    # frame itself, the ROI slice below would collapse to zero width/
    # height and the alpha-blend broadcast would crash (numpy shape
    # mismatch). Rather than let a pipeline stage fail on an unusually
    # small frame, shrink the card proportionally to fit - this keeps
    # the video rendering robust even if a future map source ever
    # returns a smaller-than-expected background image.
    max_card_w = max(1, w - 2 * margin)
    max_card_h = max(1, h - 2 * margin)
    if cw > max_card_w or ch > max_card_h:
        shrink = min(max_card_w / cw, max_card_h / ch)
        new_w = max(1, int(cw * shrink))
        new_h = max(1, int(ch * shrink))
        card_bgra = cv2.resize(card_bgra, (new_w, new_h), interpolation=cv2.INTER_AREA)
        ch, cw = card_bgra.shape[:2]

    if anchor == "bottom-right":
        x0, y0 = w - cw - margin, h - ch - margin
    elif anchor == "bottom-left":
        x0, y0 = margin, h - ch - margin
    else:
        raise ValueError(f"Unsupported anchor: {anchor}")

    card_bgr = card_bgra[:, :, :3].astype(np.float32)
    card_alpha = (card_bgra[:, :, 3].astype(np.float32) / 255.0) * alpha

    roi = out[y0:y0 + ch, x0:x0 + cw].astype(np.float32)

    # Standard "over" alpha compositing, vectorized across the whole
    # region-of-interest in one numpy expression instead of a per-pixel
    # Python loop - the difference between a microsecond blend and a
    # multi-millisecond one at this resolution.
    blended = card_bgr * card_alpha[..., None] + roi * (1 - card_alpha[..., None])
    out[y0:y0 + ch, x0:x0 + cw] = blended.astype(np.uint8)
    return out


# =======================================================================
# STEP 4: PATH INTERPOLATION (used by both Phase 1 and Phase 3)
# =======================================================================
def _get_exact_path(pts_list: list, frames: int) -> np.ndarray:
    """
    Straight-line (linear) interpolation through the exact input
    points, reparameterized by cumulative distance so the dot moves at
    constant speed regardless of how unevenly the original GPS points
    are spaced along the route.
    """
    # De-duplicate near-identical consecutive points (GPS noise while
    # stationary) so the spline isn't fit against zero-length segments.
    filtered_pts = [pts_list[0]]
    for p in pts_list[1:]:
        if np.hypot(p[0] - filtered_pts[-1][0], p[1] - filtered_pts[-1][1]) > 0.1:
            filtered_pts.append(p)

    pts = np.array(filtered_pts, dtype=float)
    diffs = np.diff(pts, axis=0)
    dists = np.hypot(diffs[:, 0], diffs[:, 1])
    cum_dists = np.concatenate(([0], np.cumsum(dists)))
    total_dist = cum_dists[-1]

    # Parameterize by fraction of total distance travelled, not by
    # point index - this is what makes playback speed constant even
    # when input points are unevenly spaced.
    t = cum_dists / total_dist if total_dist > 0 else np.linspace(0, 1, len(pts))
    t_fine = np.linspace(0, 1, frames)

    k = min(1, len(pts) - 1)  # linear spline (degree 1)
    sx = make_interp_spline(t, pts[:, 0], k=k)
    sy = make_interp_spline(t, pts[:, 1], k=k)
    return np.vstack([sx(t_fine), sy(t_fine)]).T


# =======================================================================
# STEP 5: H.264 RE-ENCODE (raw AVI from OpenCV -> compressed MP4)
# =======================================================================
def reencode_to_h264(src: str, dst: str) -> bool:
    """
    OpenCV's VideoWriter with the XVID fourcc produces a large,
    poorly-compressed AVI. We shell out to ffmpeg to transcode it into
    a properly compressed, widely-compatible H.264 MP4. Returns False
    (rather than raising) if ffmpeg isn't available or the transcode
    fails, so the caller can fall back to shipping the AVI instead of
    hard-failing the whole pipeline over a codec issue.
    """
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


# =======================================================================
# STEP 6: THE MAIN ORCHESTRATOR - renders all four phases into one MP4
# =======================================================================
def render_route_animation(
    img_path: str,
    points: list,
    labels: list,
    popups: list = None,               # type: ignore
    output_path: str = "data\\outputs\\videoroute_animation.mp4",
    fps: int = 30,
    duration_seconds: float = 8.0,
    line_color: tuple = (0, 200, 255),
    line_thickness: int = 10,
    marker_color: tuple = (0, 0, 255),
    marker_radius: int = 18,
    res_sequence: list = None,         # type: ignore
    res_duration_per_slice: float = 5.0,
    pause_seconds: float = 2.0,
    # --- Phase 4 (summary card) parameters ---
    summary: dict = None,              # type: ignore  e.g. {"total_distance_km": 0.65, "total_duration_seconds": 600}
    summary_hold_seconds: float = 4.0,
    summary_fade_seconds: float = 0.5,
):
    """
    Renders the full navigation video in four sequential phases and
    writes it to `output_path`. See the module docstring at the top of
    this file for a description of each phase.
    """
    # ---- Load the big-picture map image ----
    img = cv2.imread(img_path)
    if img is None:
        raise FileNotFoundError(f"Cannot read: {img_path}")

    h, w = img.shape[:2]
    font = cv2.FONT_HERSHEY_SIMPLEX

    # ---- Set up the video writer. We always write raw XVID/AVI first,
    # then re-encode to H.264/MP4 as a separate step (see Step 5) ----
    tmp_avi = tempfile.mktemp(suffix=".avi")
    video = cv2.VideoWriter(tmp_avi, cv2.VideoWriter_fourcc(*"XVID"), fps, (w, h))  # type: ignore
    if not video.isOpened():
        raise RuntimeError("OpenCV VideoWriter failed.")

    # ==========================================
    # PHASE 1: BIG PICTURE ROUTE
    # ==========================================
    num_frames = max(10, int(duration_seconds * fps))

    # Pre-compute which points actually have a visible landmark label,
    # once, outside the per-frame loop - avoids re-filtering every frame.
    named = [
        (int(points[i][0]), int(points[i][1]), labels[i])
        for i in range(len(points)) if _is_real_label(labels[i])
    ]

    base_img = img.copy()  # clean background, no landmarks baked in
    smooth_path = _get_exact_path(points, num_frames)
    path_history: list[tuple[int, int]] = []
    last_frame = base_img.copy()

    # Bundle popup metadata with its coordinates up front so the
    # per-frame distance check below is a simple lookup, not a
    # re-derivation of which points have popups.
    active_popups = []
    if popups:
        for i in range(len(points)):
            if popups[i] is not None:
                active_popups.append({
                    "x": points[i][0],
                    "y": points[i][1],
                    "data": popups[i],
                    "label": labels[i],
                })

    print(f"🎬 Rendering Phase 1: Big Picture ({duration_seconds}s)")
    for p in smooth_path:
        frame = base_img.copy()
        path_history.append((int(p[0]), int(p[1])))

        # 1. Trailing line showing the path travelled so far.
        if len(path_history) > 1:
            pts_arr = np.array(path_history, dtype=np.int32)
            cv2.polylines(frame, [pts_arr], False, line_color, line_thickness, cv2.LINE_AA)

        # 2. Landmarks drawn on top of the line so they stay legible.
        for x, y, lbl in named:
            draw_landmark(frame, x, y, lbl, radius=16, font=font)

        # 3. The leading dot drawn last, on top of everything else.
        cx_, cy_ = path_history[-1]
        cv2.circle(frame, (cx_, cy_), marker_radius, marker_color, -1, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), marker_radius + 4, (255, 255, 255), 2, cv2.LINE_AA)
        cv2.circle(frame, (cx_, cy_), marker_radius + 7, marker_color, 1, cv2.LINE_AA)

        # --- Popup logic: freeze briefly on a photo card when the dot
        # passes within 5px of a waypoint that has one attached ---
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

                        border = 8
                        total_w = pw + (border * 2)
                        total_h = ph + (border * 2)

                        # Preferred placement: above and to the right of the dot.
                        box_x = int(popup["x"]) + 20
                        box_y = int(popup["y"]) - total_h - 20

                        # Clamp so the popup box never renders off-screen.
                        box_x = max(0, min(box_x, w - total_w))
                        box_y = max(0, min(box_y, h - total_h))

                        cv2.rectangle(freeze_frame, (box_x, box_y), (box_x + total_w, box_y + total_h), (255, 255, 255), -1)
                        cv2.rectangle(freeze_frame, (box_x, box_y), (box_x + total_w, box_y + total_h), (100, 100, 100), 2)

                        paste_y = box_y + border
                        paste_x = box_x + border
                        freeze_frame[paste_y:paste_y + ph, paste_x:paste_x + pw] = pop_img

                freeze_frames_count = int(popup["data"]["freeze_seconds"] * fps)
                for _ in range(freeze_frames_count):
                    video.write(freeze_frame)
        # --- end popup logic ---

        last_frame = frame
        video.write(frame)

    # ==========================================
    # PHASE 2: THE PAUSE
    # ==========================================
    pause_frames = int(pause_seconds * fps)
    print(f"⏸️  Pausing for {pause_seconds}s")
    for _ in range(pause_frames):
        video.write(last_frame)

    # ==========================================
    # PHASE 3: RESIDENTIAL MAPS (loop through zoomed-in slices)
    # ==========================================
    if res_sequence:
        for i, res_data in enumerate(res_sequence):
            print(f" Rendering Residential Map {i + 1}/{len(res_sequence)}")

            res_img = cv2.imread(res_data["img_path"])
            res_points = res_data["points"]
            res_labels = res_data["labels"]

            if res_img is not None:
                # Guard against a residential map image whose pixel
                # dimensions don't exactly match the main video canvas.
                if res_img.shape[:2] != (h, w):
                    res_img = cv2.resize(res_img, (w, h))

                res_base = res_img.copy()
                res_named = [
                    (int(res_points[j][0]), int(res_points[j][1]), res_labels[j])
                    for j in range(len(res_points)) if _is_real_label(res_labels[j])
                ]

                res_frames = max(10, int(res_duration_per_slice * fps))
                res_smooth_path = _get_exact_path(res_points, res_frames)
                res_history: list[tuple[int, int]] = []

                for p in res_smooth_path:
                    frame = res_base.copy()
                    res_history.append((int(p[0]), int(p[1])))

                    if len(res_history) > 1:
                        pts_arr = np.array(res_history, dtype=np.int32)
                        cv2.polylines(frame, [pts_arr], False, line_color, line_thickness, cv2.LINE_AA)

                    for x, y, lbl in res_named:
                        draw_landmark(frame, x, y, lbl, radius=16, font=font)

                    cx_, cy_ = res_history[-1]
                    cv2.circle(frame, (cx_, cy_), marker_radius, marker_color, -1, cv2.LINE_AA)
                    cv2.circle(frame, (cx_, cy_), marker_radius + 4, (255, 255, 255), 2, cv2.LINE_AA)
                    cv2.circle(frame, (cx_, cy_), marker_radius + 7, marker_color, 1, cv2.LINE_AA)

                    video.write(frame)
                    last_frame = frame

                # Small pause before jumping to the next residential slice.
                for _ in range(fps):
                    video.write(last_frame)

    # ==========================================
    # PHASE 4: FREEZE FRAME + SUMMARY CARD (distance / time spent)
    # ==========================================
    if summary:
        print(f"🧾 Rendering summary card ({summary_hold_seconds}s)")

        # Rendered ONCE, reused across every frame below - see the
        # detailed rationale in render_summary_card()'s docstring.
        card = render_summary_card(
            distance_km=summary.get("total_distance_km", 0.0),
            duration_seconds=summary.get("total_duration_seconds", 0.0),
        )

        fade_frames = max(1, int(summary_fade_seconds * fps))
        hold_frames = max(0, int(summary_hold_seconds * fps) - fade_frames)

        # Fade-in: alpha ramps linearly 0 -> 1 across fade_frames, all
        # composited onto the SAME frozen last_frame from whichever
        # phase finished last (Phase 1 or Phase 3) - this is what
        # makes it read as "navigation paused here" rather than a
        # jarring hard-cut onto a blank frame.
        for i in range(fade_frames):
            alpha = (i + 1) / fade_frames
            frame = composite_card_on_frame(last_frame, card, alpha=alpha)
            video.write(frame)

        # Hold at full opacity for the remainder of the requested duration.
        held_frame = composite_card_on_frame(last_frame, card, alpha=1.0)
        for _ in range(hold_frames):
            video.write(held_frame)

    # ---- Finalize the raw AVI, then try to re-encode to H.264 MP4 ----
    video.release()
    print("✅ Frames written ✓")

    output_path = str(output_path)
    if output_path.lower().endswith(".mp4") and reencode_to_h264(tmp_avi, output_path):
        os.remove(tmp_avi)
        total_dur = (
            duration_seconds
            + pause_seconds
            + (len(res_sequence) * res_duration_per_slice if res_sequence else 0)
            + (summary_hold_seconds if summary else 0)
        )
        print(f"🎥 Saved Final Video → '{output_path}' ({total_dur}s total, H.264)")
    else:
        # ffmpeg missing/failed - ship the AVI rather than losing the
        # render entirely. The caller can detect this by checking the
        # returned path's suffix.
        avi_out = str(Path(output_path).with_suffix(".avi"))
        os.rename(tmp_avi, avi_out)
        print(f"⚠️  ffmpeg not found — saved as AVI → '{avi_out}'")
        output_path = avi_out

    return output_path


# =======================================================================
# CLI ENTRY POINT
# =======================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--output", default="data\\outputs\\video\\route_animation.mp4")
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--thickness", type=int, default=None)
    parser.add_argument("--radius", type=int, default=None)

    # --- Phase 3 (residential maps) ---
    parser.add_argument("--res-map", default=None, help="Path to the residential map image")
    parser.add_argument("--res-route", default=None, help="Path to the residential JSON route")
    parser.add_argument("--res-duration", type=float, default=12.0, help="Duration for the residential animation")
    parser.add_argument("--pause", type=float, default=2.0, help="Pause seconds between maps")

    # --- Phase 4 (summary card) ---
    parser.add_argument("--summary-json", default=None,
                         help="Path to a JSON file with {'total_distance_km':.., 'total_duration_seconds':..}")
    parser.add_argument("--summary-hold", type=float, default=4.0, help="Seconds the summary card stays on screen")
    parser.add_argument("--summary-fade", type=float, default=0.5, help="Seconds for the summary card fade-in")

    args = parser.parse_args()

    # Load Phase 1 data
    points, labels, popups, settings = load_route(args.route)

    # Load Phase 3 data and structure it into a sequence
    res_sequence = None
    if args.res_route and args.res_map:
        res_points, res_labels, _, _ = load_route(args.res_route)
        res_sequence = [{
            "img_path": args.res_map,
            "points": res_points,
            "labels": res_labels,
        }]

    # Load Phase 4 data (distance/time summary), if provided
    summary = None
    if args.summary_json:
        with open(args.summary_json, "r", encoding="utf-8") as f:
            summary = json.load(f)

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
        res_sequence=res_sequence,  # type: ignore
        res_duration_per_slice=args.res_duration,
        pause_seconds=args.pause,
        summary=summary,  # type: ignore
        summary_hold_seconds=args.summary_hold,
        summary_fade_seconds=args.summary_fade,
    )


if __name__ == "__main__":
    main()