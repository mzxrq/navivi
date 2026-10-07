"""Text drawn into the video (HUD, cards, intro/outro labels), one catalog per language.

Catalogs are assets/config/labels_<lang>.json; a new language is one more file, layered over
Japanese then English so a missing key never breaks a render. The language comes from the
project setting `video_text_language` ("auto", "ja", "en", ...). "auto" follows the job_config's
top-level `map_language`, which the app writes from its UI language on every save; a config with
no `map_language` (saved before the app wrote it) stays Japanese, so old projects keep their look.
"""

import copy
import json
import os
import re
from functools import lru_cache
from typing import Any, Dict, Optional

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "config")
DEFAULT_LANGUAGE = "ja"
FALLBACK_CHAIN = ("ja", "en")

# Used only when labels_ja.json is missing from a broken install.
_BUILTIN_JA: Dict[str, Any] = {
    "mode_name": {"walking": "歩く", "driving": "運転", "car": "運転", "ferry": "乗船", "airplane": "飛行機"},
    "mode_duration_label": {
        "walking": "歩く時間", "driving": "運転時間", "car": "運転時間", "ferry": "乗船時間", "airplane": "飛行時間",
    },
    "en_route_suffix": {"ferry": " 乗船中", "airplane": " 搭乗中"},
    "separator": " ・ ", "mode_join": "・", "total_label": "合計", "distance_label": "距離", "taskbar_card_title": "旅の概要",
    "waypoint_fallback": "ウェイポイント", "start_prefix": "出発: ", "stop_prefix": "到着: ",
    "soon_banner": "まもなく {dest}", "en_route_banner": "{dest} へ{suffix}", "hud_minutes": "{n} 分",
    "duration_seconds": "{n}秒", "duration_hours_minutes": "{h}時間{m:02d}分", "duration_minutes": "{m}分",
    "duration_fallback": "時間", "destination_fallback": "目的地", "overview_start": "開始", "overview_end": "終点",
    "place_count": "{n} か所", "outro_subtitle": "訪れた{count}か所", "outro_route_from": "{name} から",
    "outro_summary": {
        "distance": "総距離", "legs": "{count}区間", "time": "移動時間", "time_note": "目安",
        "places": "訪れた場所", "places_value": "{count}か所", "longest": "最長区間",
    },
}


def _read(lang: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(_CONFIG_DIR, f"labels_{lang}.json"), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@lru_cache(maxsize=None)
def available_languages() -> tuple:
    try:
        names = os.listdir(_CONFIG_DIR)
    except OSError:
        return FALLBACK_CHAIN
    found = []
    for name in names:
        m = re.fullmatch(r"labels_([a-z]{2,3}(?:-[A-Za-z]+)?)\.json", name)
        if m:
            found.append(m.group(1))
    return tuple(sorted(found)) or FALLBACK_CHAIN


@lru_cache(maxsize=None)
def _catalog(lang: str) -> Dict[str, Any]:
    merged = _read("ja") or _BUILTIN_JA
    if lang != "ja":
        for step in ("en", lang):
            layer = _read(step)
            if layer:
                merged = _merge(merged, layer)
    return merged


def labels_for(language: Optional[str]) -> Dict[str, Any]:
    """The full label catalog for a language code; an unknown code gives Japanese. A fresh copy."""
    lang = (language or DEFAULT_LANGUAGE).lower().replace("_", "-")
    if lang not in available_languages():
        lang = DEFAULT_LANGUAGE
    return copy.deepcopy(_catalog(lang))


def resolve_language(setting: Optional[str] = None, map_language: Optional[str] = None) -> str:
    """Setting "auto" (or nothing) follows map_language; no map_language at all means an old config: Japanese."""
    choice = str(setting or "auto").lower().replace("_", "-")
    if choice != "auto":
        return choice if choice in available_languages() else DEFAULT_LANGUAGE
    if not isinstance(map_language, str) or not map_language.strip():
        return DEFAULT_LANGUAGE
    base = map_language.lower().replace("_", "-").split("-")[0]
    if base == "ja":
        return "ja"
    return base if base in available_languages() else "en"


def current_language() -> str:
    """The language for the project being rendered, read off the process-wide job config."""
    from services.config.job_config import JobConfigManager

    instance = JobConfigManager._instance
    if instance is None or not getattr(instance, "_initialized", False):
        return DEFAULT_LANGUAGE
    settings = instance.get_settings()
    setting = settings.get("video_text_language") if isinstance(settings, dict) else None
    return resolve_language(setting, instance.get("map_language"))


def current_labels() -> Dict[str, Any]:
    return labels_for(current_language())


def plural(labels: Dict[str, Any], key: str, number: int, **fields: Any) -> str:
    """labels[key] formatted with fields; exactly one uses labels[key + "_one"] when the catalog has it."""
    template = labels.get(f"{key}_one") if number == 1 else None
    return (template or labels[key]).format(**fields)


def strip_waypoint_prefixes(text: str) -> str:
    """Removes the start/arrival prefix render_step puts on a stop's label, whichever language wrote it.

    Japanese strips as it always did (anywhere in the text); other languages only at the very start,
    because a bare word like "Arrival" can be part of a real place name.
    """
    for lang in available_languages():
        labels = _catalog(lang)
        for key in ("start_prefix", "stop_prefix"):
            prefix = labels[key]
            if lang == "ja":
                text = text.replace(prefix, "").replace(prefix.strip(": "), "")
            elif text.startswith(prefix):
                text = text[len(prefix):]
            elif text == prefix.strip(": "):
                text = ""
    return text.strip()
