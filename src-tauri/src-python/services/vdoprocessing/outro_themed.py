"""The themed scroll outro: one place at a time, held, then every box rolls its contents on to the next.
Used for a project with a themed hud.json; otherwise outrocard.py draws its own scroll."""

from __future__ import annotations

import base64
import io
import math
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageOps

from services import tuning, video_text
from services.hudtheme import cards, layout, model, render, styles
from services.localization.route_brief import clean_label, on_route
from services.vdoprocessing import outrocard
from services.vdoprocessing.route_inputs import same_place, stopby_labels


_HEIGHT = 600  # the layout's height; video px = layout px * height / 600
_BOXES = 6  # that roll, each starting after the one before (designs/outro)
_SEEK_JS = "t => document.getAnimations().forEach(a => { a.pause(); a.currentTime = t * 1000; })"
# A description keeps its size: its box grows with it, from 3 lines to the 7 that still fit the screen.
_GROW_JS = """() => {
    for (const text of document.querySelectorAll('.desc')) {
        const line = parseFloat(getComputedStyle(text).lineHeight);
        const lines = Math.max(3, Math.min(7, Math.ceil(text.scrollHeight / line - 0.1)));
        text.style.height = lines * line + 'px';
        if (text.scrollHeight > lines * line + 1)
            Object.assign(text.style, { display: '-webkit-box', webkitBoxOrient: 'vertical', webkitLineClamp: '7' });
        text.closest('.about').style.setProperty('--h-' + text.parentElement.dataset.screen, lines * line + 38 + 'px');
    }
}"""


# Written beside an outro clip that is themed (its title is in the picture).
MARKER = Path(tuning.OUTRO_OUTPUT_FILENAME).with_suffix(".themed.json").name


class Screen(NamedTuple):
    badge: str
    name: str
    description: str
    photo: Optional[str]
    km: Optional[float]  # of the leg arriving here; None when no leg does
    minutes: Optional[int]


def _description(waypoint: Dict[str, Any]) -> str:
    return str(waypoint.get("outroDescription") or "").strip()


def themed_screens(
    waypoints: List[Dict[str, Any]], brief: Optional[Dict[str, Any]], stopbys: bool = True, closed: bool = True,
) -> List[Screen]:
    """Every stop in route order, described or not; `stopbys` (stops skipped in video export too) and `closed`
    places as the outro storyboard says. A place come back to gets one screen: the visit with the description."""
    places = [w for w in waypoints if isinstance(w, dict) and "lat" in w]
    listed = {id(w): badge for badge, w in outrocard._route_badges(places)}
    labels = stopby_labels(places)
    route = [w for w in places if on_route(w)]
    legs = (brief or {}).get("legs") or []
    arriving = {id(w): leg for w, leg in zip(route[1:], legs)}

    chosen: List[Tuple[int, Dict[str, Any]]] = []
    for pos, wp in enumerate(places):
        if wp.get("inaccessible"):
            if not closed:
                continue
        elif (wp.get("isStopBy") or wp.get("skipAssetGeneration")) and not stopbys:
            continue
        again = next((n for n, (_, other) in enumerate(chosen)
                      if same_place(wp, other) and not (wp.get("isStopBy") or other.get("isStopBy"))), None)
        if again is None:
            chosen.append((pos, wp))
        elif _description(wp) and not _description(chosen[again][1]):
            chosen[again] = (pos, wp)

    screens = []
    for pos, wp in sorted(chosen, key=lambda item: item[0]):
        badge = listed.get(id(wp)) or ("×" if wp.get("inaccessible") else labels.get(pos, "・"))
        leg = arriving.get(id(wp))
        screens.append(Screen(
            badge, clean_label(wp), _description(wp), outrocard._first_image(wp),
            leg["km"] if leg else None, leg["minutes"] if leg else None,
        ))
    return screens


def _timing(fps: int) -> Tuple[int, int, int]:
    """(first screen's hold, roll, other holds) in frames."""
    return tuple(int(round(s * fps)) for s in (
        tuning.OUTRO_THEMED_FIRST_HOLD_SECONDS, tuning.OUTRO_THEMED_ROLL_SECONDS, tuning.OUTRO_THEMED_HOLD_SECONDS))


def frame_times(count: int, fps: int) -> List[float]:
    """The animation time (s) each video frame shows. Whole frame numbers, so a hold repeats one value exactly."""
    first, scroll, hold = _timing(fps)
    times = [0.0] * first
    for k in range(count - 1):
        start = first + k * (scroll + hold)
        times += [(start + j) / fps for j in range(1, scroll + 1)]
        times += [(start + scroll) / fps] * hold
    return times


def _seconds() -> Tuple[float, float, float]:
    """_timing in seconds, rounded to whole video frames as frame_times is: a tuned value never drifts."""
    return tuple(frames / tuning.INTRO_FPS for frames in _timing(tuning.INTRO_FPS))


def scroll_keyframes(count: int, delay: float = 0.0, length: Optional[float] = None) -> List[Tuple[float, int]]:
    """(percent of the whole animation, screen shown) at each end of every hold, for a box that starts `delay`
    seconds into each roll and takes `length` seconds (None: the whole roll)."""
    first, roll, hold = _seconds()
    length = roll if length is None else length
    seconds = animation_seconds(count)
    frames = [(0.0, 0)]
    for index in range(1, count):
        leave = first + (index - 1) * (roll + hold) + delay
        frames += [(leave, index - 1), (leave + length, index)]
    frames.append((seconds, count - 1))
    # Rounded down: a held frame must be at or past its keyframe, or the screen before still shows.
    return [(min(100.0, math.floor(at / seconds * 1e6 + 1e-3) / 1e4), index) for at, index in frames]


def animation_seconds(count: int) -> float:
    first, scroll, hold = _seconds()
    return first + max(0, count - 1) * (scroll + hold)


def outro_theme(project_dir: Path, settings: Dict, waypoints: List[Dict], style: str) -> Optional[Dict]:
    """The loaded theme when this outro is to be themed, else None (today's outro)."""
    if style != "scroll":
        return None
    hud = layout.read(project_dir)
    if hud is None:
        return None
    theme_id = model.resolve_theme(hud["theme"], [str(w.get("routeMode") or "walking") for w in waypoints], 0.0)
    return model.load_theme(theme_id, model.is_dark(settings)) if theme_id else None


def _photo_uri(path: Optional[str], width: float, scale: float) -> str:
    """The photo as a data URI at the size it is shown (the page loads no files); "" for the theme's picture."""
    if not path:
        return ""
    try:
        with Image.open(path) as image:
            photo = ImageOps.fit(
                ImageOps.exif_transpose(image).convert("RGB"), (round(width * scale), round(172 * scale)))
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return ""
    buffer = io.BytesIO()
    photo.save(buffer, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def page_html(screens: List[Screen], theme: Dict, heading: Dict, size: Tuple[int, int]) -> str:
    """Every place stacked in its boxes on one page (designs/outro), with their paused roll animations."""
    width, scale = size[0] * _HEIGHT / size[1], size[1] / _HEIGHT
    left = (width * 0.8 - 76) * 318 / 674  # the photo column, in the mockup's proportion to the figures
    labels = video_text.current_labels()
    unknown_km, unknown_time = "--.- km", "--"
    shown = []
    for s in screens:
        known = s.km is not None
        shown.append({
            "badge": s.badge, "name": s.name, "description": s.description, "photo": _photo_uri(s.photo, left - 8, scale),
            "known": known, "km": outrocard._fmt_km(s.km) if known else unknown_km,
            "time": video_text.format_duration(labels, s.minutes * 60) if known else unknown_time,
        })
    for item, following in zip(shown, shown[1:] + [None]):
        item["next"] = following and {key: following[key] for key in ("badge", "name", "photo")}
    return cards._card(
        "outro", styles.DEFAULT, theme, width, _HEIGHT, screens=shown, left=left,
        kicker=heading.get("kicker") or "", title=heading.get("title") or "", subtitle=heading.get("subtitle") or "",
        distance_label=labels["distance_label"], time_label=labels["duration_fallback"],
        unknown_km=unknown_km, unknown_time=unknown_time,
        keyframes=scroll_keyframes(len(screens)), seconds=animation_seconds(len(screens)),
        rolls=[scroll_keyframes(len(screens), box * tuning.OUTRO_THEMED_BOX_STAGGER_SECONDS,
                                tuning.OUTRO_THEMED_BOX_ROLL_SECONDS) for box in range(_BOXES)],
    ).html


def open_page(browser, html: str, size: Tuple[int, int]):
    """The page at the video's size: bundled fonts only, no network, no script of its own, text fitted."""
    scale = size[1] / _HEIGHT
    page = browser.new_page(
        device_scale_factor=scale, viewport={"width": math.ceil(size[0] / scale), "height": _HEIGHT},
        java_script_enabled=False,
    )
    page.route("**/*", lambda route: route.abort())
    page.route(render._HOST + "*", render._serve_font)  # the later route wins
    page.set_content(render._page_html())
    page.evaluate("html => { document.body.style.padding = '0'; document.body.innerHTML = html; }", html)
    page.evaluate(render._FIT_JS)
    page.evaluate(_GROW_JS)
    return page


def _shot(page, size: Tuple[int, int]) -> Image.Image:
    return Image.open(io.BytesIO(page.screenshot())).convert("RGB").crop((0, 0, *size))


def capture_frames(html: str, times: Sequence[float], size: Tuple[int, int]) -> Iterator[np.ndarray]:
    """The page at each animation time as an RGB frame; a repeated time (a hold) is not captured again."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])  # never the GPU: this machine crashes
        try:
            page = open_page(browser, html, size)
            shown = frame = None
            for t in times:
                if t != shown:
                    page.evaluate(_SEEK_JS, t)
                    shown, frame = t, np.asarray(_shot(page, size))
                yield frame
        finally:
            browser.close()


def capture_backdrop(html: str, size: Tuple[int, int]) -> Image.Image:
    """The background artwork alone, without the banner and the screens."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        try:
            page = open_page(browser, html, size)
            page.evaluate("() => document.body.classList.add('bare')")
            return _shot(page, size)
        finally:
            browser.close()


def _with_logos(frames: Iterator[np.ndarray], end_card: np.ndarray, fps: int) -> Iterator[np.ndarray]:
    for frame in frames:
        yield frame
    yield from outrocard._logo_tail(frame, end_card, fps)


def write_themed_outro(
    output_path: Path, screens: List[Screen], theme: Dict, heading: Dict, size: Tuple[int, int], fps: int,
) -> bool:
    """The themed clip: every screen, then the logos over the same background."""
    html = page_html(screens, theme, heading, size)
    ink = tuple(int(theme["ink"][i:i + 2], 16) for i in (1, 3, 5))
    end_card = outrocard._end_card(size, capture_backdrop(html, size), text_color=ink)
    captured = capture_frames(html, frame_times(len(screens), fps), size)
    try:
        frames = captured if end_card is None else _with_logos(captured, end_card, fps)
        return outrocard._pipe_frames(frames, output_path, fps, size)
    finally:
        captured.close()  # the browser goes now, even when ffmpeg failed
