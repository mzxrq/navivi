"""Where the Mapbox access token comes from.

The token is an app-wide setting: the desktop app hands it to every Python process as `NAVIVI_MAPBOX_TOKEN`, so it is
never part of a project file. The older sources stay as fallbacks so a CLI run and projects saved by earlier versions
(which still carry `settings.mapbox_api_key`) keep working.

Kept dependency-free so any module can import it. It does not load `.env` files; the modules that already do
(`maptile.py`, `pydeckrecorder/common.py`) have filled `os.environ` by the time a token is asked for.
"""

import os
from typing import Mapping, Optional

ENV_VAR = "NAVIVI_MAPBOX_TOKEN"

# [NOTE] [Map] Order matters: the app's own value first, then what an older project file carried, then the old env names.
_SETTING_KEYS = ("mapbox_api_key", "mapbox_access_token")
_LEGACY_ENV_VARS = ("MAPBOX_API_KEY", "MAPBOX_ACCESS_TOKEN", "VITE_MAPBOX_TOKEN")


def _clean(value) -> Optional[str]:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def resolve_mapbox_token(settings: Optional[Mapping] = None) -> Optional[str]:
    """The token to use, or None when there is none (callers then fall back to the free Esri tiles)."""
    token = _clean(os.environ.get(ENV_VAR))
    if token:
        return token
    for key in _SETTING_KEYS:
        token = _clean((settings or {}).get(key))
        if token:
            return token
    for name in _LEGACY_ENV_VARS:
        token = _clean(os.environ.get(name))
        if token:
            return token
    return None
