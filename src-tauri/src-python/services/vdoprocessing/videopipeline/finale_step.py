"""The finale before the outro: the last stop's photo appears as a small pinned card first, then that same
card's picture grows to fill the frame — the hand-off into the next beat — before the camera pulls back from
there until the whole route is in view (real map tiles every frame: pydeck_overview's ending push-in, played
backwards). Nothing walks.

It lands on the overview's own recap picture, drawn the same way that screen is: the route in the project's
colour, each stop a plain colour dot, and every stop's slim pill badge (its pin's glyph, its name down the
capsule, its photo) laid out by the recap's own layout. Three things carry the data in as it arrives - the
route unspools backwards out of the close-up, each badge lands in turn as the line passes it, and the summary
card's distance and time tick up to the real figures. Then the outro cuts in."""

import csv
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Tuple

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


# The route finishes drawing itself this far into the pull-back, leaving the
# rest of it for the stops' own badges to come in over.
_ROUTE_DRAW_FRACTION = 0.7
# One stop's badge after another, and how long each takes to fade in.
_BADGE_STEP_SECONDS = 0.12
_BADGE_FADE_SECONDS = 0.25
# The summary card's distance and time tick up over this long, finishing with
# the last badge.
_COUNT_UP_SECONDS = 1.1


def _stop_colors(badge: str, settings: dict) -> Tuple[int, int, int]:
    """The RGB a stop's dot takes, by the same roles the overview's pins use
    (pins.py's _pin_label_and_color): S green, E purple, a stop-by brown, a
    closed place red, everything else the colour a reached stop's pin ends
    the overview in. Read through render_look's own _project_color, which
    knows the app writes these settings as RGB while the renderers draw in
    BGR — outrocard's reader assumes BGR and hands back the project's own
    colours channel-swapped (its cyan route arrives as orange)."""
    from .render_look import _arrived_marker_color, _project_color

    bgr = {
        "S": tuning.START_PIN_COLOR,
        "E": tuning.END_PIN_COLOR,
        "・": tuning.STOPBY_PIN_COLOR,
        "×": tuning.CLOSED_PIN_COLOR,
    }.get(badge)
    if bgr is None:
        marker = _project_color(settings, "marker_color", tuning.DEFAULT_MARKER_COLOR)
        bgr = _arrived_marker_color(settings, marker)  # by the recap, every stop has been reached
    return tuple(int(c) for c in reversed(bgr))


def _map_frame(frame_bgr, extent, route, stops, line_bgr, line_px, drawn: float) -> Image.Image:
    """One map frame of the pull-back, overlaid the way the overview's recap
    screen is: the route in the project's own colour under a white halo, and
    each stop marked by a plain colour dot — no numbered pin, since the
    number lives in that stop's badge. `drawn` (0-1) is how much of the
    route is on yet: it unspools BACKWARDS, from the last stop the camera
    opens on toward the start, so the walk replays out of the close-up
    instead of creeping in from off-screen. Each stop's dot lands as the
    line reaches it."""
    h, w = frame_bgr.shape[:2]
    from services.mapfetcher.mapgeometry import RouteGeometryProcessor as G

    frame = frame_bgr.copy()
    upto = max(2, int(len(route) * min(max(drawn, 0.0), 1.0)))
    first = len(route) - upto
    pts = np.array(
        [G.project_latlon_to_pixel(la, lo, extent, w, h) for la, lo in route[first:]], dtype=np.float64
    )
    pts = np.clip(pts, -3 * w, 4 * w).astype(np.int32)
    cv2.polylines(frame, [pts], False, (255, 255, 255), line_px + 4, cv2.LINE_AA)
    cv2.polylines(frame, [pts], False, line_bgr, line_px, cv2.LINE_AA)
    img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    d = ImageDraw.Draw(img)
    r = max(4, int(h // 150))
    for stop in stops:
        if stop["at"] < first:
            continue
        x, y = G.project_latlon_to_pixel(stop["lat"], stop["lon"], extent, w, h)
        if -r <= x <= w + r and -r <= y <= h + r:
            d.ellipse([x - r, y - r, x + r, y + r], fill=stop["color"], outline="white", width=max(2, r // 2))
    return img


def _recap_badges(engine, stops, extent, size, reserved, route_px):
    """Every stop laid out as the overview recap lays its pill badges out —
    same slim capsules, same no-overlap lattice, no leader lines — by borrowing the recap's own layout (_layout_recap_cards)
    with this clip's graphics engine. Returns them in the order the recap
    would reveal them. [] for a stop set it can't place."""
    from services.vdoprocessing.spatial_renderer.pins import _PinMixin
    from services.vdoprocessing.spatial_renderer.popups import _PopupMixin

    class _RecapLayout(_PopupMixin, _PinMixin):
        pass

    from services.mapfetcher.mapgeometry import RouteGeometryProcessor as G

    from services.vdoprocessing.route_inputs import same_place

    w, h = size
    popups, places = [], []
    for stop in stops:
        if not stop["photo"]:
            continue
        # One badge per PLACE, as the overview recap (_recap_popup_set): a return stop, or a loop's E back at
        # S, is a second visit to a place already badged. A stop-by is always its own place.
        if stop["badge"] != "・":
            if any(same_place(stop, p) for p in places):
                continue
            places.append(stop)
        x, y = G.project_latlon_to_pixel(stop["lat"], stop["lon"], extent, w, h)
        if not (0 <= x <= w and 0 <= y <= h):
            continue
        popups.append({
            "x": float(x), "y": float(y), "index": stop["index"], "order": stop["order"],
            "badge_label": stop["badge"], "label": stop["name"],
            "border_color": tuple(reversed(stop["color"])),  # the engine draws in BGR
            "data": {"popup_image": str(stop["photo"]), "arrived": True},
        })
    if not popups:
        return []
    layout = _RecapLayout()
    layout.config = {}
    layout.graphics = engine
    try:
        # No leader lines, as every other recap (the badge's number and its dot's colour are the tie): with
        # them the badges were all strung along the top, their lines crossing the whole map.
        return layout._layout_recap_cards(popups, w, h, reserved_boxes=reserved, route_obstacles=route_px,
                                          leaders=False)
    except Exception as exc:  # a layout that can't place them is no reason to lose the clip
        logger.warning("Finale: no recap badges (%s).", exc, exc_info=True)
        return []


def _with_badges(img: Image.Image, engine, badges, alphas) -> Image.Image:
    """`img` with each badge drawn at its own alpha, lines first and then the
    capsules — the recap's own order, so no line lands on top of a badge."""
    frame = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    shown = [(b, a) for b, a in zip(badges, alphas) if a > 0.01]
    for badge, alpha in shown:
        hud = badge.copy()
        hud["hud_corner"] = None
        hud["draw_leader_line"] = not badge.get("suppress_leader_line")
        hud["leader_line_color"] = badge.get("recap_line_color") or badge.get("border_color")
        frame = engine.render_popup_box(frame, hud, alpha=alpha, line_only=True)
    for badge, alpha in shown:
        hud = badge.copy()
        hud["hud_corner"] = None
        hud["draw_leader_line"] = False
        frame = engine.render_popup_box(frame, hud, alpha=alpha, skip_line=True)
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))


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


def _graphics(settings: dict):
    """The engine this clip draws its badges and summary card with, set up
    the way the overview sets its own up so both look the same."""
    from services.mapfetcher.graphicengine import GraphicsEngine

    return GraphicsEngine(
        summary_card_style=settings.get("summary_card_style", tuning.DEFAULT_SUMMARY_CARD_STYLE),
        summary_card_labels=settings.get("summary_card_labels"),
        theme=tuning.resolve_ui_theme(settings),
    )


def _summary_card(engine, config_path: Path):
    """render(fraction) -> BGRA summary card for the whole route, the one the
    overview ends on. `fraction` (0-1) scales the distance and the times, so
    the finale can tick them up to the real figures. None without a brief."""
    try:
        from services.localization.overview_script import course_summary
        from services.localization.route_brief import load_brief

        summary = course_summary(load_brief(str(config_path)))

        def render(fraction: float = 1.0):
            k = min(max(fraction, 0.0), 1.0)
            return engine.render_summary_card(
                distance_km=summary["total_distance_km"] * k,
                duration_seconds=summary["total_duration_seconds"] * k,
                mode_breakdown={m: v * k for m, v in (summary["mode_breakdown"] or {}).items()},
                mode_duration={m: v * k for m, v in (summary["mode_duration"] or {}).items()},
            )

        return render
    except Exception as exc:
        logger.warning("Finale: no summary card (%s).", exc, exc_info=True)
        return None


def _photo_path(photo, project_dir: Path) -> Path:
    """A stop's photo as a path: absolute as given, else under the project."""
    return Path(photo) if photo and Path(photo).is_absolute() else project_dir / str(photo or "")


def _last_stop_photo(last: dict, project_dir: Path):
    """(lat, lon, photo path) of the last stop, or None (logged) when it has no photo or position."""
    from services.vdoprocessing.outrocard import _first_image

    photo = _first_image(last)
    photo_path = _photo_path(photo, project_dir)
    lat, lon = last.get("lat"), last.get("lng", last.get("lon"))
    if lat is None or lon is None or not photo or not photo_path.exists():
        logger.info("Finale: the last stop has no photo or position - skipping.")
        return None
    return lat, lon, photo_path


def _finale_stops(badges, route, project_dir: Path, settings: dict) -> list:
    """Each stop as the recap knows it: where it is, the colour its dot takes, the glyph and photo its badge
    shows, and the point along the track the drawing route reaches it at (so its dot lands then)."""
    from services.vdoprocessing.outrocard import _first_image

    stops, order = [], 0
    for index, (badge, wp) in enumerate(badges):
        if wp.get("lat") is None:
            continue
        wp_lat, wp_lon = wp["lat"], wp.get("lng", wp.get("lon"))
        if badge.isdigit():
            order = int(badge)
        wp_photo = _first_image(wp)
        wp_photo_path = _photo_path(wp_photo, project_dir)
        at = min(
            range(len(route)),
            key=lambda i: (route[i][0] - wp_lat) ** 2 + (route[i][1] - wp_lon) ** 2,
        )
        stops.append({
            "badge": badge, "index": index, "order": order,
            "lat": wp_lat, "lon": wp_lon, "at": at,
            "name": wp.get("label") or wp.get("name") or "",
            "color": _stop_colors(badge, settings),
            "photo": wp_photo_path if wp_photo and wp_photo_path.exists() else None,
        })
    return stops


# The clip opens on the fullscreen photo, so the voice starts with it.
_VOICE_START_SECONDS = 0.0


def _hold_seconds(voice) -> float:
    """The whole-route hold, stretched so the voice ends inside the clip."""
    before_hold = tuning.FINALE_PHOTO_SECONDS + tuning.FINALE_ZOOM_SECONDS
    hold_seconds = tuning.FINALE_HOLD_SECONDS
    if voice:
        hold_seconds = max(
            hold_seconds, _VOICE_START_SECONDS + voice[1] + tuning.FINALE_VOICE_TAIL_SECONDS - before_hold
        )
    return hold_seconds


def _clip_key(project_dir: Path, settings: dict, size, voice, stops: list, photo_path: Path) -> str:
    from . import clip_cache

    return clip_cache.fingerprint(
        {
            "settings": settings, "size": size, "voice": voice and voice[1],
            "stops": [
                (s["badge"], s["lat"], s["lon"], s["name"], str(s["photo"] or "")) for s in stops
            ],
        },
        [
            gps_data_dir(project_dir) / "gpsdata.csv", photo_path, voice and voice[0],
            __file__, tuning.__file__,
            # the recap badge layout the finale borrows
            Path(__file__).parents[1] / "spatial_renderer" / "popups.py",
        ],
    )


def _pull_back_maps(settings: dict, route, stops: list, size, fps: int, lat, lon) -> tuple:
    """(frames, maps): the pydeck pull-back, close-up first, and each frame overlaid with the route and stops."""
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
    # [NOTE] The overview's own route colour, read the way render_look reads it (the app writes RGB), not the
    # way outrocard does, which hands back the project's cyan as orange.
    from .render_look import _project_color

    line_bgr = _project_color(settings, "line_color", tuning.MODE_LINE_COLORS["walking"])
    line_px = int(settings.get("line_thickness") or 6)
    # The route traces itself over the first part of the pull-back, then stays whole for the rest of it.
    maps = [
        _map_frame(
            f, ext, route, stops, line_bgr, line_px,
            drawn=_ease((i + 1) / max(1, len(frames) * _ROUTE_DRAW_FRACTION)),
        )
        for i, (f, ext) in enumerate(frames)
    ]
    return frames, maps


_SUMMARY_MARGIN = 20


def _summary_box(card_render, out_w: int, out_h: int) -> list:
    """The summary card's corner, reserved from the badge layout; [] without a card."""
    if card_render is None:
        return []
    sample = card_render(1.0)
    return [(
        out_w - sample.shape[1] - _SUMMARY_MARGIN, out_h - sample.shape[0] - _SUMMARY_MARGIN,
        float(out_w - _SUMMARY_MARGIN), float(out_h - _SUMMARY_MARGIN),
    )]


class _Scene(NamedTuple):
    """What the finale's frames are drawn from."""
    fps: int
    size: Tuple[int, int]
    full: Image.Image  # the last stop's photo, fitted to the frame
    engine: object
    card_render: Optional[Callable]
    maps: list
    frames: list
    lat: float
    lon: float
    badges: list
    hold_seconds: float
    card_w: int
    card_h: int


def _build_scene(
    settings: dict, config_path: Path, photo_path: Path, route, stops: list, frames: list, maps: list,
    size, fps: int, lat, lon, hold_seconds: float,
) -> _Scene:
    """Loads the photo and the graphics, and lays every stop's pill badge out on the view the pull-back ends on
    exactly as the recap lays them out."""
    from services.mapfetcher.mapgeometry import RouteGeometryProcessor as G

    out_w, out_h = size
    full = ImageOps.fit(Image.open(photo_path).convert("RGB"), size, Image.LANCZOS)
    engine = _graphics(settings)
    card_render = _summary_card(engine, config_path)
    card_w = int(out_w * 0.2)
    card_h = int(card_w * out_h / out_w)
    final_extent = frames[-1][1]
    summary_box = _summary_box(card_render, out_w, out_h)
    route_px = np.array(
        [G.project_latlon_to_pixel(la, lo, final_extent, out_w, out_h) for la, lo in route],
        dtype=float,
    )
    recap_badges = _recap_badges(engine, stops, final_extent, size, summary_box, route_px)
    # Revealed in the order the route itself unspools past them: the last stop first, back to the start.
    recap_badges.sort(key=lambda b: -int(b.get("index", 0)))
    return _Scene(fps, size, full, engine, card_render, maps, frames, lat, lon, recap_badges, hold_seconds, card_w, card_h)


def _card_box(scene: _Scene, i: int) -> Tuple[float, float, float, float]:
    """(left, top, pin x, pin y) of the photo card on pull-back frame `i`."""
    from services.mapfetcher.mapgeometry import RouteGeometryProcessor as G

    out_w, out_h = scene.size
    px, py = G.project_latlon_to_pixel(float(scene.lat), float(scene.lon), scene.frames[i][1], out_w, out_h)
    left = min(max(px - scene.card_w / 2, 16), out_w - scene.card_w - 16)
    top = min(max(py - scene.card_h - 40, 16), out_h - scene.card_h - 16)
    return left, top, px, py


def _with_card(scene: _Scene, base: Image.Image, box, scale: float, alpha: float, leader: float, pin) -> Image.Image:
    img = base.copy()
    left, top, w, h = box
    if leader > 0 and pin:
        d = ImageDraw.Draw(img, "RGBA")
        d.line([(left + w / 2, top + h), (pin[0], pin[1] - 4)], fill=(255, 255, 255, int(255 * leader)), width=3)
    if alpha > 0:
        cw, ch = max(1, int(w * scale)), max(1, int(h * scale))
        photo_img = scene.full.resize((cw, ch), Image.LANCZOS)
        mask = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=int(14 * (1 - min(1.0, w / scene.size[0]))) + 2, fill=int(255 * alpha))
        img.paste(photo_img, (int(left + (w - cw) / 2), int(top + (h - ch) / 2)), mask)
    return img


def _pull_back_frames(scene: _Scene):
    """Opens on the fullscreen photo, which the pull-back then shrinks back onto its pin and fades off it."""
    out_w, out_h = scene.size
    for _ in range(int(tuning.FINALE_PHOTO_SECONDS * scene.fps)):
        yield np.asarray(scene.full)
    shrink = max(1, int(len(scene.maps) * 0.35))
    fade = max(1, int(len(scene.maps) * 0.3))
    for i, base in enumerate(scene.maps):
        left, top, px, py = _card_box(scene, i)
        t = _ease(min(1.0, i / shrink))
        box = tuple(
            a + (b - a) * t
            for a, b in zip((0.0, 0.0, float(out_w), float(out_h)), (left, top, float(scene.card_w), float(scene.card_h)))
        )
        f = min(1.0, max(0.0, (i - shrink) / fade))
        yield np.asarray(_with_card(scene, base, box, 1 - 0.4 * f, 1 - f, (1 - f) * t, (px, py)))


def _hold_frames(scene: _Scene):
    """The whole route in shot: each stop's badge arrives in turn, the summary card fades in and its distance
    and time tick up to the real figures, and the finished picture (the recap's) is held."""
    fps, badges, card_render = scene.fps, scene.badges, scene.card_render
    step = max(1, int(_BADGE_STEP_SECONDS * fps))
    badge_fade = max(1, int(_BADGE_FADE_SECONDS * fps))
    count_frames = max(1, int(_COUNT_UP_SECONDS * fps))
    card_fade = max(1, int(0.4 * fps))
    settled = None
    for i in range(int(scene.hold_seconds * fps)):
        alphas = [min(1.0, max(0.0, (i - j * step) / badge_fade)) for j in range(len(badges))]
        done = all(a >= 1.0 for a in alphas)
        if done and settled is not None:
            yield settled
            continue
        img = _with_badges(scene.maps[-1], scene.engine, badges, alphas) if badges else scene.maps[-1]
        if card_render is None:
            frame_rgb = np.asarray(img)
        else:
            counted = card_render(min(1.0, (i + 1) / count_frames))
            frame = scene.engine.composite_card_on_frame(
                cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR),
                counted, alpha=min(1.0, (i + 1) / card_fade),
            )
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if done and i + 1 >= count_frames:
            settled = frame_rgb  # nothing moves after this; reuse it
        yield frame_rgb


def _finale_frames(scene: _Scene):
    yield from _pull_back_frames(scene)
    yield from _hold_frames(scene)


def render_finale_clip(project_config_path: str, force: bool = False) -> Optional[str]:
    """98_finale.mp4, or None (never raises) when it is switched off, there is no track or photo, or it fails."""
    config_path = Path(project_config_path)
    try:
        job_config = JobConfigManager(config_path)
        settings = job_config.get("settings", {}) or {}
        if not settings.get("enable_finale", tuning.DEFAULT_ENABLE_FINALE) or not settings.get("enable_outro", tuning.DEFAULT_ENABLE_OUTRO):
            return None
        project_dir = Path(job_config.get("directory_path") or config_path.parent)
        from services.vdoprocessing.outrocard import _pipe_frames, _route_badges
        from . import clip_cache
        from .outro_step import _route_frame_size

        badges = _route_badges(job_config.get("waypoints", []) or [])
        route = route_latlon(project_dir)
        if len(badges) < 2 or len(route) < 2:
            logger.info("Finale: no route track or stops yet - skipping.")
            return None
        last = _last_stop_photo(badges[-1][1], project_dir)
        if last is None:
            return None
        lat, lon, photo_path = last
        stops = _finale_stops(badges, route, project_dir, settings)

        video_dir = project_video_dir(project_dir)
        size = _route_frame_size(Path(video_dir)) or (1920, 1080)
        fps = int(settings.get("fps") or tuning.INTRO_FPS)
        voice = finale_voice({"settings": settings}, project_dir)
        hold_seconds = _hold_seconds(voice)

        out = Path(video_dir) / tuning.FINALE_OUTPUT_FILENAME
        key = _clip_key(project_dir, settings, size, voice, stops, photo_path)
        if not force and clip_cache.reusable(project_dir, out, key):
            return str(out)

        frames, maps = _pull_back_maps(settings, route, stops, size, fps, lat, lon)
        scene = _build_scene(
            settings, config_path, photo_path, route, stops, frames, maps, size, fps, lat, lon, hold_seconds
        )
        part = out.with_name(out.stem + ".part.mp4")
        if not _pipe_frames(_finale_frames(scene), part, fps, size):
            return None
        part.replace(out)
        from services.vdoprocessing.cliptiming import timing_sidecar_path, write_audio_offset

        if voice:
            write_audio_offset(str(out), _VOICE_START_SECONDS)  # the timeline plays the narration from here
        else:
            Path(timing_sidecar_path(str(out))).unlink(missing_ok=True)
        clip_cache.remember(project_dir, out, key)
        logger.info("Finale clip generated: %s", out)
        return str(out)
    except Exception:
        logger.warning("Finale clip failed - the outro follows the last stop directly.", exc_info=True)
        return None
