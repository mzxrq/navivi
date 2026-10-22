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
            out.append({"lat": lat, "lon": lon, "popup_image": str(cache_dir / cached), "passing": True})
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
            out.append({"lat": lat, "lon": lon, "popup_image": str(cache_dir / name), "passing": True})
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
    resp = get(API, params={
        "access_token": token,
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
