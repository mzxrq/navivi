"""Street-level photos at a leg's turns, from Mapillary (CC-BY-SA, credited on each photo)."""

import io
import json
import math
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
from PIL import Image, ImageDraw, ImageOps

from services.localization.leg_script import TURN_DEG, leg_turns
from services.logger.logger import setup_logger

logger = setup_logger("StreetPhotos")

ENV_VAR = "NAVIVI_MAPILLARY_TOKEN"
API = "https://graph.mapillary.com/images"
SEARCH_M = 30.0
ZIGZAG_M = 100.0  # turns closer than this along the leg share one photo
NEAR_STOP_M = 50.0  # a turn this close to the start or the destination gets no photo
SEARCH_LIMIT = 10  # one small page per turn
REQUEST_GAP_S = 0.5  # at most 2 requests a second, searches and downloads together
CREDIT = "© Mapillary (CC BY-SA)"
CREDIT_WITH_USER = "© {user} / Mapillary (CC BY-SA)"
CARD_ASPECT = 16 / 9  # the pop-up card's shape (the 1920x1080 frame's), so the card never crops the credit
CREDIT_STRIP_SHARE = 0.11  # of the image height; about 12 px on the 200 px card
CREDIT_STRIP_COLOR = (20, 20, 24)


def resolve_mapillary_token() -> Optional[str]:
    """App-wide, like the Mapbox token: the desktop app passes it in the environment."""
    value = os.environ.get(ENV_VAR)
    return value.strip() if value and value.strip() else None


def _pick(images: List[Dict], lat: float, lon: float, bearing: float) -> Optional[Dict]:
    """The photo looking most nearly down the new street; nearer wins a tie."""
    def score(img):
        angle = img.get("compass_angle")
        off = abs((float(angle) - bearing + 180.0) % 360.0 - 180.0) if angle is not None else 180.0
        x, y = img["geometry"]["coordinates"]
        dist = math.hypot((x - lon) * 111320.0 * math.cos(math.radians(lat)), (y - lat) * 110540.0)
        return (round(off / 15.0), dist)

    usable = [img for img in images if img.get("thumb_1024_url") and img.get("geometry")]
    return min(usable, key=score) if usable else None


def _download(content: bytes, path: Path, username: Optional[str] = None) -> None:
    """Saved as a CARD_ASPECT image: the photo filling the top, the credit in a dark strip under it,
    so the card shows all of it (no cover crop cutting the credit off) and nothing covers the photo."""
    from services.mapfetcher.graphicengine.base import _GraphicsEngineBase
    from services.vdoprocessing.outrocard import _load_font

    photo = Image.open(io.BytesIO(content)).convert("RGB")
    w = photo.width
    h = round(w / CARD_ASPECT)
    strip = round(h * CREDIT_STRIP_SHARE)
    card = Image.new("RGB", (w, h), CREDIT_STRIP_COLOR)
    card.paste(ImageOps.fit(photo, (w, h - strip), Image.LANCZOS), (0, 0))
    text = CREDIT_WITH_USER.format(user=username) if username else CREDIT
    draw = ImageDraw.Draw(card)
    size = round(strip * 0.7)
    while True:  # a long name shrinks to fit the strip
        font = _load_font(_GraphicsEngineBase.FONT_CANDIDATES_BOLD, size)  # thin strokes went grey on the small card
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
        if x1 - x0 <= w - strip or size <= 8:
            break
        size -= 2
    draw.text((w - strip // 2 - (x1 - x0) - x0, h - strip + (strip - (y1 - y0)) // 2 - y0), text, font=font, fill=(255, 255, 255))
    tmp = path.with_suffix(".part")
    card.save(tmp, "JPEG", quality=90)
    os.replace(tmp, path)


def _photo_turns(turns: List[Dict]) -> List[Dict]:
    """The turns worth a photo (and its API calls): one per run of turns less than ZIGZAG_M apart (a zigzag
    is one photo), the sharpest of the run, and only a real turn (TURN_DEG, read as 曲がって, not a bend
    read as 寄って) that is not at either stop, whose own photo is on screen there."""
    groups: List[List[Dict]] = []
    for turn in turns:
        if turn["at"] < NEAR_STOP_M or turn["to_end"] < NEAR_STOP_M:
            continue
        if groups and turn["at"] - groups[-1][-1]["at"] < ZIGZAG_M:
            groups[-1].append(turn)
        else:
            groups.append([turn])
    sharpest = (max(group, key=lambda t: abs(t["angle"])) for group in groups)
    return [t for t in sharpest if abs(t["angle"]) >= TURN_DEG]


def _load_index(path: Path) -> Dict[str, Optional[str]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_index(path: Path, index: Dict[str, Optional[str]]) -> None:
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def turn_photos(points: List[List[float]], cache_dir: Path, token: str) -> List[Dict]:
    """[{"lat", "lon", "popup_image"}] for each photo-worthy turn of the leg [[lat, lon], ...] that has coverage.

    index.json remembers each turn's answer (a file name, or None for no coverage), so an unchanged
    route makes no requests at all; failed requests are not remembered and retry on the next run."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    index_path = cache_dir / "index.json"
    index = _load_index(index_path)
    changed, refused, last_call = False, False, [0.0]

    def polite_get(url, **kwargs):
        wait = last_call[0] + REQUEST_GAP_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        last_call[0] = time.monotonic()
        resp = requests.get(url, timeout=20, **kwargs)
        resp.raise_for_status()
        return resp

    out = []
    for turn in _photo_turns(leg_turns(points)["turns"]):
        lat, lon = turn["lat"], turn["lon"]
        key = f"{lat:.5f},{lon:.5f},{round(turn['bearing'] / 15.0) * 15 % 360}"
        cached = index.get(key, False)
        if cached and (cache_dir / cached).exists():
            out.append({"lat": lat, "lon": lon, "popup_image": str(cache_dir / cached), "passing": True, "street_view": True})
            continue
        if cached is None or refused:
            continue
        try:
            name = _mapillary(polite_get, token, lat, lon, turn["bearing"], cache_dir)
        except requests.HTTPError as e:
            logger.warning("Mapillary refused the turn at %.5f,%.5f (%s); no more requests this leg.", lat, lon, e)
            refused = True
            continue
        except (requests.RequestException, ValueError, OSError) as e:
            logger.warning("Mapillary photo for the turn at %.5f,%.5f failed: %s", lat, lon, e)
            continue
        index[key], changed = name, True
        if name:
            out.append({"lat": lat, "lon": lon, "popup_image": str(cache_dir / name), "passing": True, "street_view": True})
        else:
            logger.info("No Mapillary photo near the turn at %.5f,%.5f.", lat, lon)
    if changed:
        try:
            _save_index(index_path, index)
        except OSError as e:
            logger.warning("Could not save the street photo index: %s", e)
    return out


def _mapillary(get, token, lat, lon, bearing, cache_dir: Path) -> Optional[str]:
    dlat = SEARCH_M / 110540.0
    dlon = SEARCH_M / (111320.0 * math.cos(math.radians(lat)))
    # The token goes in a header: in the URL it was written to app.log with every refused request's error.
    resp = get(API, headers={"Authorization": f"OAuth {token}"}, params={
        "bbox": f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}",
        "fields": "id,thumb_1024_url,compass_angle,geometry,creator",
        "limit": SEARCH_LIMIT,
    })
    img = _pick(resp.json().get("data") or [], lat, lon, bearing)
    if img is None:
        return None
    name = f"{img['id']}.jpg"
    if not (cache_dir / name).exists():
        _download(get(img["thumb_1024_url"]).content, cache_dir / name, (img.get("creator") or {}).get("username"))
    return name

def card_title(label: Optional[str]) -> str:
    """A street view's name for its card; "" for the app's automatic "Street view 3" (en/ja; never shown)."""
    import re

    label = (label or "").strip()
    return "" if re.fullmatch(r"(Street view|\u30b9\u30c8\u30ea\u30fc\u30c8\u30d3\u30e5\u30fc)\s*\d*", label) else label


def clear_of(photos: List[Dict], views: List[Dict], meters: float) -> List[Dict]:
    """The automatic turn photos that are not within `meters` of a street view the user placed (that corner
    already has its photo)."""
    return [
        p for p in photos
        if all(_meters(p["lat"], p["lon"], v["lat"], v["lon"]) > meters for v in views)
    ]


def _meters(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    k = math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot((a_lat - b_lat) * 110540.0, (a_lon - b_lon) * 111320.0 * k)


def _meters_to_segment(lat: float, lon: float, a, b) -> float:
    """Metres from (lat, lon) to the segment a-b (each (lat, lon)), on a local flat projection."""
    k = math.cos(math.radians(lat))
    ax, ay = (float(a[1]) - lon) * 111320.0 * k, (float(a[0]) - lat) * 110540.0
    bx, by = (float(b[1]) - lon) * 111320.0 * k, (float(b[0]) - lat) * 110540.0
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    return math.hypot(ax + t * dx, ay + t * dy)


def street_view_landmarks(
    street_views: List[Dict], legs_latlon: List[List[List[float]]], project_dir, cues: Optional[List[List[tuple]]] = None,
) -> List[List[Dict]]:
    """The project's street view waypoints (job_config `street_views`) as pop-up photo cards, per leg: each goes to the
    one leg whose track passes nearest, within tuning.STREET_VIEW_MAX_OFF_ROUTE_M. On a leg they are in the order the
    walker passes them; the n-th takes the leg's n-th {view} cue (`cues[leg]`: [(piece, show s, hide s)]) and pops in
    and out on the voice, the rest pop in at their spot for the turn-photo time."""
    from services import tuning

    out: List[List[Dict]] = [[] for _ in legs_latlon]
    for sv in street_views or []:
        image = sv.get("image")
        if not image or sv.get("lat") is None or sv.get("lng") is None:
            continue
        best = None
        for leg, track in enumerate(legs_latlon):
            for k in range(len(track)):
                # To the line between this point and the next (a long straight stretch has its points far apart).
                d = _meters_to_segment(float(sv["lat"]), float(sv["lng"]), track[k], track[min(k + 1, len(track) - 1)])
                if best is None or d < best[0]:
                    best = (d, leg, k)
        if best is None or best[0] > tuning.STREET_VIEW_MAX_OFF_ROUTE_M:
            logger.info("Street view %s is %s from every leg; not shown.", sv.get("label") or sv.get("id"),
                        "far" if best else "with no leg")
            continue
        path = Path(image)
        out[best[1]].append({
            "lat": float(sv["lat"]), "lon": float(sv["lng"]), "passing": True, "street_view": True, "_at": best[2],
            "popup_image": str(path if path.is_absolute() else (Path(project_dir) / path).resolve()),
            **({"label": card_title(sv.get("label"))} if card_title(sv.get("label")) else {}),
        })
    for leg, cards in enumerate(out):
        cards.sort(key=lambda c: c.pop("_at"))
        attach_cue_spans(cards, cues[leg] if cues and leg < len(cues) else [])
    return out


def attach_cue_spans(cards: List[Dict], spans: List[tuple]) -> List[Dict]:
    """A named span ({view:X}, 5th item X) takes the card whose name is or contains X; the other spans go to the other
    cards in walk order. Span: (piece, show, hide[, wait[, name]]). Cards with no span keep their spot."""
    free, unnamed = list(cards), []
    for cue in spans or []:
        name = str(cue[4]).strip() if len(cue) > 4 and cue[4] else ""
        card = next((c for c in free if name and name in (c.get("label") or "")), None)
        if name and card is None:
            logger.warning("{view:%s}: no street view with that name on this leg; it takes the next one.", name)
        if card is None:
            unnamed.append(cue)
        else:
            free.remove(card)
            _attach(card, cue)
    for card, cue in zip(free, unnamed):
        _attach(card, cue)
    return cards


def _attach(card: Dict, cue: tuple) -> None:
    piece, show, hide, *rest = cue
    card.update(piece=int(piece), show_seconds=round(float(show), 2), hide_seconds=round(float(hide), 2))
    if rest and rest[0]:
        card["wait"] = True


def view_cue_spans(times: Dict[str, float], piece: int, kind: str = "view") -> List[tuple]:
    """[(piece, show, hide)] from one narration's measured cue times (view1/viewend1, …; kind "turn": turn1/…), in
    order: kept to STREET_VIEW_MIN … MAX seconds, and never running into the next card's show time. A {view wait}
    (viewwait1, …) adds a 4th item, True: the walker waits at the card's spot."""
    from services import tuning

    spans = []
    n = 1
    while f"{kind}{n}" in times:
        show = float(times[f"{kind}{n}"])
        hide = float(times.get(f"{kind}end{n}", show))
        hide = min(max(hide, show + tuning.STREET_VIEW_MIN_SECONDS), show + tuning.STREET_VIEW_MAX_SECONDS)
        name = next((k.split(":", 1)[1] for k in times if k.startswith(f"{kind}name{n}:")), "")  # {view:X}
        spans.append([show, hide, f"{kind}wait{n}" in times, name])
        n += 1
    for a, b in zip(spans, spans[1:]):
        a[1] = min(a[1], b[0])
    return [(piece, s, h, w, x) if x else (piece, s, h, True) if w else (piece, s, h) for s, h, w, x in spans]
