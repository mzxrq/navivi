"""Street-level photos at a leg's turns, from Mapillary (CC-BY-SA, credited on each photo)."""

import io
import json
import math
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

import requests
from PIL import Image, ImageDraw, ImageFont

from services.localization.leg_script import leg_turns
from services.logger.logger import setup_logger

logger = setup_logger("StreetPhotos")

ENV_VAR = "NAVIVI_MAPILLARY_TOKEN"
API = "https://graph.mapillary.com/images"
SEARCH_M = 30.0
ZIGZAG_M = 100.0  # turns closer than this along the leg share one photo
SEARCH_LIMIT = 10  # one small page per turn
REQUEST_GAP_S = 0.5  # at most 2 requests a second, searches and downloads together
CREDIT = "© Mapillary, CC-BY-SA"


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


def _download(content: bytes, path: Path) -> None:
    """Saved with the CC-BY-SA credit stamped in a corner, so it is on screen whenever the photo is."""
    img = Image.open(io.BytesIO(content)).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(max(12, img.height // 40))
    x0, y0, x1, y1 = draw.textbbox((0, 0), CREDIT, font=font)
    pad = font.size // 2
    at = (img.width - (x1 - x0) - 2 * pad, img.height - (y1 - y0) - 2 * pad)
    draw.text((at[0] + pad - x0, at[1] + pad - y0), CREDIT, font=font, fill="white", stroke_width=2, stroke_fill="black")
    tmp = path.with_suffix(".part")
    img.save(tmp, "JPEG", quality=90)
    os.replace(tmp, path)


def _photo_turns(turns: List[Dict]) -> List[Dict]:
    """One turn per run of turns less than ZIGZAG_M apart (a zigzag is one photo): the sharpest of the run."""
    groups: List[List[Dict]] = []
    for turn in turns:
        if groups and turn["at"] - groups[-1][-1]["at"] < ZIGZAG_M:
            groups[-1].append(turn)
        else:
            groups.append([turn])
    return [max(group, key=lambda t: abs(t["angle"])) for group in groups]


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
    """[{"lat", "lon", "popup_image"}] for each turn of the leg [[lat, lon], ...] that has coverage.

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
        if key in index and (index[key] is None or (cache_dir / index[key]).exists()):
            if index[key]:
                out.append({"lat": lat, "lon": lon, "popup_image": str(cache_dir / index[key]), "passing": True})
            continue
        if refused:
            continue
        dlat = SEARCH_M / 110540.0
        dlon = SEARCH_M / (111320.0 * math.cos(math.radians(lat)))
        try:
            resp = polite_get(API, params={
                "access_token": token,
                "bbox": f"{lon - dlon},{lat - dlat},{lon + dlon},{lat + dlat}",
                "fields": "id,thumb_1024_url,compass_angle,geometry",
                "limit": SEARCH_LIMIT,
            })
            img = _pick(resp.json().get("data") or [], lat, lon, turn["bearing"])
            if img is None:
                logger.info("No Mapillary photo near the turn at %.5f,%.5f.", lat, lon)
                index[key], changed = None, True
                continue
            name = f"{img['id']}.jpg"
            if not (cache_dir / name).exists():
                _download(polite_get(img["thumb_1024_url"]).content, cache_dir / name)
        except requests.HTTPError as e:
            logger.warning("Mapillary refused the turn at %.5f,%.5f (%s); no more requests this leg.", lat, lon, e)
            refused = True
            continue
        except (requests.RequestException, ValueError, OSError) as e:
            logger.warning("Mapillary photo for the turn at %.5f,%.5f failed: %s", lat, lon, e)
            continue
        index[key], changed = name, True
        out.append({"lat": lat, "lon": lon, "popup_image": str(cache_dir / name), "passing": True})
    if changed:
        try:
            _save_index(index_path, index)
        except OSError as e:
            logger.warning("Could not save the street photo index: %s", e)
    return out
