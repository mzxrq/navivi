"""The finale before the outro: the last stop's photo fills the frame and shrinks onto its pin, then the camera pulls
back from there until the whole route is in view (real map tiles every frame: pydeck_overview's ending push-in,
played backwards). Nothing walks: the whole line is drawn from the start. It ends on the route summary card the
overview ends with (total distance and time per mode), then the outro cuts in."""

import csv
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from services import tuning
from services.config.job_config import JobConfigManager
from services.projectfiles import gps_data_dir

from .helpers import logger, project_video_dir


def route_latlon(project_dir: Path) -> List[Tuple[float, float]]:
    """The walked track as (lat, lon), from the GPS step's csv; [] when it isn't there yet."""
    path = gps_data_dir(project_dir) / "gpsdata.csv"
    out = []
    try:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    out.append((float(row["latitude"]), float(row["longitude"])))
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    return out


def _ease(t: float) -> float:
    t = min(max(t, 0.0), 1.0)
    return t * t * (3 - 2 * t)


def _overlay(frame_bgr, extent, route, stops, line_bgr, line_px, marker_rgb) -> Image.Image:
    """One map frame with the whole route line and every stop's badge (S, 1 … E) drawn on it."""
    h, w = frame_bgr.shape[:2]
    from services.mapfetcher.mapgeometry import RouteGeometryProcessor as G

    frame = frame_bgr.copy()
    pts = np.array([G.project_latlon_to_pixel(la, lo, extent, w, h) for la, lo in route], dtype=np.float64)
    pts = np.clip(pts, -3 * w, 4 * w).astype(np.int32)
    cv2.polylines(frame, [pts], False, (255, 255, 255), line_px + 4, cv2.LINE_AA)
    cv2.polylines(frame, [pts], False, line_bgr, line_px, cv2.LINE_AA)
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    from services.mapfetcher.graphicengine import _GraphicsEngineBase
    from services.vdoprocessing.outrocard import _load_font

    d = ImageDraw.Draw(img)
    r = max(12, h // 54)
    font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_BOLD, int(r * 1.2))
    for badge, lat, lon in stops:
        x, y = G.project_latlon_to_pixel(lat, lon, extent, w, h)
        if -r <= x <= w + r and -r <= y <= h + r:
            d.ellipse([x - r, y - r, x + r, y + r], fill=marker_rgb, outline="white", width=max(2, r // 5))
            d.text((x, y), badge, font=font, fill="white", anchor="mm")
    return img


def finale_voice(project_config: dict, project_dir: Path) -> Optional[Tuple[Path, float]]:
    """(wav, seconds) of the finale narration when the project has one and its voice was made for these words."""
    from .audio_step import FINALE_NARRATION_FILENAME, finale_script
    from .helpers import project_audio_dir

    script = finale_script(project_config)
    wav = Path(project_audio_dir(project_dir)) / FINALE_NARRATION_FILENAME
    if not script or not wav.exists():
        return None
    try:
        import soundfile as sf

        return wav, float(sf.info(str(wav)).duration)
    except Exception:
        return None


def _summary_card(config_path: Path, settings: dict):
    """(engine, BGRA card): the overview's ending summary card for the whole route; None without a route brief."""
    try:
        from services.localization.overview_script import course_summary
        from services.localization.route_brief import load_brief
        from services.mapfetcher.graphicengine import GraphicsEngine

        summary = course_summary(load_brief(str(config_path)))
        engine = GraphicsEngine(
            summary_card_style=settings.get("summary_card_style", tuning.DEFAULT_SUMMARY_CARD_STYLE),
            summary_card_labels=settings.get("summary_card_labels"),
            theme=tuning.resolve_ui_theme(settings),
        )
        card = engine.render_summary_card(
            distance_km=summary["total_distance_km"], duration_seconds=summary["total_duration_seconds"],
            mode_breakdown=summary["mode_breakdown"], mode_duration=summary["mode_duration"],
        )
        return engine, card
    except Exception as exc:
        logger.info("Finale: no summary card (%s).", exc)
        return None


def render_finale_clip(project_config_path: str, force: bool = False) -> Optional[str]:
    """98_finale.mp4, or None (never raises) when it is switched off, there is no track or photo, or it fails."""
    config_path = Path(project_config_path)
    try:
        job_config = JobConfigManager(config_path)
        settings = job_config.get("settings", {}) or {}
        if not settings.get("enable_finale", tuning.DEFAULT_ENABLE_FINALE) or not settings.get("enable_outro", tuning.DEFAULT_ENABLE_OUTRO):
            return None
        project_dir = Path(job_config.get("directory_path") or config_path.parent)
        from services.vdoprocessing.outrocard import _first_image, _project_colors, _route_badges

        badges = _route_badges(job_config.get("waypoints", []) or [])
        route = route_latlon(project_dir)
        if len(badges) < 2 or len(route) < 2:
            logger.info("Finale: no route track or stops yet - skipping.")
            return None
        last = badges[-1][1]
        photo = _first_image(last)
        photo_path = Path(photo) if photo and Path(photo).is_absolute() else project_dir / str(photo or "")
        lat, lon = last.get("lat"), last.get("lng", last.get("lon"))
        if lat is None or lon is None or not photo or not photo_path.exists():
            logger.info("Finale: the last stop has no photo or position - skipping.")
            return None
        stops = [(b, wp["lat"], wp.get("lng", wp.get("lon"))) for b, wp in badges if wp.get("lat") is not None]

        from .outro_step import _route_frame_size

        video_dir = project_video_dir(project_dir)
        size = _route_frame_size(Path(video_dir)) or (1920, 1080)
        out_w, out_h = size
        fps = int(settings.get("fps") or tuning.INTRO_FPS)
        voice = finale_voice({"settings": settings}, project_dir)
        # The voice starts as the photo shrinks; the whole-route hold stretches so it ends inside the clip.
        voice_start = tuning.FINALE_PHOTO_SECONDS
        before_hold = tuning.FINALE_PHOTO_SECONDS + 0.7 + 0.6 + tuning.FINALE_ZOOM_SECONDS
        hold_seconds = tuning.FINALE_HOLD_SECONDS
        if voice:
            hold_seconds = max(hold_seconds, voice_start + voice[1] + tuning.FINALE_VOICE_TAIL_SECONDS - before_hold)

        from . import clip_cache

        out = Path(video_dir) / tuning.FINALE_OUTPUT_FILENAME
        key = clip_cache.fingerprint(
            {"settings": settings, "stops": stops, "size": size, "voice": voice and voice[1]},
            [gps_data_dir(project_dir) / "gpsdata.csv", photo_path, voice and voice[0], __file__, tuning.__file__],
        )
        if not force and clip_cache.reusable(project_dir, out, key):
            return str(out)

        lats, lons = [p[0] for p in route], [p[1] for p in route]
        pad_lat, pad_lon = (max(lats) - min(lats)) * 0.12 + 1e-4, (max(lons) - min(lons)) * 0.12 + 1e-4
        bbox = {"min_lat": min(lats) - pad_lat, "max_lat": max(lats) + pad_lat, "min_lon": min(lons) - pad_lon, "max_lon": max(lons) + pad_lon}
        from services.mapbox_token import resolve_mapbox_token
        from services.mapfetcher.maplanguage import resolve_map_style
        from services.mapfetcher.pydeck_overview import capture_pydeck_zoom_sequence

        n = max(2, int(tuning.FINALE_ZOOM_SECONDS * fps))
        frames = capture_pydeck_zoom_sequence(
            bbox, size, float(lat), float(lon), n, zoom_boost=tuning.FINALE_ZOOM_BOOST,
            mapbox_key=resolve_mapbox_token(settings), map_style=resolve_map_style(settings, "mapbox/streets-v12"),
            route_latlon=route,
        )[::-1]  # pulls back: the close-up first
        colors = _project_colors(settings)
        line_bgr = tuple(reversed(colors.get("line", (33, 150, 243))))
        marker = colors.get("marker", tuning.OUTRO_BADGE_COLOR)
        line_px = int(settings.get("line_thickness") or 6)
        maps = [_overlay(f, ext, route, stops, line_bgr, line_px, marker) for f, ext in frames]

        from services.mapfetcher.mapgeometry import RouteGeometryProcessor as G

        full = ImageOps.fit(Image.open(photo_path).convert("RGB"), size, Image.LANCZOS)
        card = _summary_card(config_path, settings)
        card_w = int(out_w * 0.2)
        card_h = int(card_w * out_h / out_w)

        def card_box(i: int) -> Tuple[float, float]:
            px, py = G.project_latlon_to_pixel(float(lat), float(lon), frames[i][1], out_w, out_h)
            left = min(max(px - card_w / 2, 16), out_w - card_w - 16)
            top = min(max(py - card_h - 40, 16), out_h - card_h - 16)
            return left, top, px, py

        def with_card(base: Image.Image, box, scale: float, alpha: float, leader: float, pin) -> Image.Image:
            img = base.copy()
            left, top, w, h = box
            if leader > 0 and pin:
                d = ImageDraw.Draw(img, "RGBA")
                d.line([(left + w / 2, top + h), (pin[0], pin[1] - 4)], fill=(255, 255, 255, int(255 * leader)), width=3)
            if alpha > 0:
                cw, ch = max(1, int(w * scale)), max(1, int(h * scale))
                photo_img = full.resize((cw, ch), Image.LANCZOS)
                mask = Image.new("L", (cw, ch), 0)
                ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=int(14 * (1 - min(1.0, w / out_w))) + 2, fill=int(255 * alpha))
                img.paste(photo_img, (int(left + (w - cw) / 2), int(top + (h - ch) / 2)), mask)
            return img

        def generate():
            left, top, px, py = card_box(0)
            small = (left, top, card_w, card_h)
            for _ in range(int(tuning.FINALE_PHOTO_SECONDS * fps)):
                yield np.asarray(full)
            k = max(1, int(0.7 * fps))
            for i in range(k):
                t = _ease((i + 1) / k)
                box = tuple(a + (b - a) * t for a, b in zip((0, 0, out_w, out_h), small))
                yield np.asarray(with_card(maps[0], box, 1.0, 1.0, max(0.0, t * 2 - 1), (px, py)))
            for _ in range(int(0.6 * fps)):
                yield np.asarray(with_card(maps[0], small, 1.0, 1.0, 1.0, (px, py)))
            # The camera pulls back; the card rides on its pin, shrinking and fading over the first part.
            for i, base in enumerate(maps):
                f = min(1.0, i / max(1, len(maps) * 0.45))
                left, top, px, py = card_box(i)
                yield np.asarray(with_card(base, (left, top, card_w, card_h), 1 - 0.4 * f, 1 - f, 1 - f, (px, py)))
            # The whole route, and the summary card fades in over it.
            last_bgr = cv2.cvtColor(np.asarray(maps[-1]), cv2.COLOR_RGB2BGR)
            k = max(1, int(0.4 * fps))
            for i in range(int(hold_seconds * fps)):
                if card is None:
                    yield np.asarray(maps[-1])
                    continue
                engine, card_bgra = card
                frame = engine.composite_card_on_frame(last_bgr, card_bgra, alpha=min(1.0, (i + 1) / k))
                yield cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        from services.vdoprocessing.outrocard import _pipe_frames

        part = out.with_name(out.stem + ".part.mp4")
        if not _pipe_frames(generate(), part, fps, size):
            return None
        part.replace(out)
        from services.vdoprocessing.cliptiming import timing_sidecar_path, write_audio_offset

        if voice:
            write_audio_offset(str(out), voice_start)  # the timeline plays the narration from here
        else:
            Path(timing_sidecar_path(str(out))).unlink(missing_ok=True)
        clip_cache.remember(project_dir, out, key)
        logger.info("Finale clip generated: %s", out)
        return str(out)
    except Exception:
        logger.warning("Finale clip failed - the outro follows the last stop directly.", exc_info=True)
        return None
