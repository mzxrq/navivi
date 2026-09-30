"""Map label language, driven by job_config's top-level `map_language` (the app's UI locale)."""

import json
from typing import Optional

# Name fields carried by Mapbox Streets v8 tiles
STREETS_LANGS = ("ar", "de", "en", "es", "fr", "it", "ja", "ko", "pt", "ru", "vi", "zh-Hans", "zh-Hant")


def streets_lang(locale: Optional[str]) -> Optional[str]:
    if not locale or not isinstance(locale, str):
        return None
    if locale in STREETS_LANGS:
        return locale
    lower = locale.lower()
    if lower.startswith("zh"):
        return "zh-Hant" if any(t in lower for t in ("tw", "hk", "mo", "hant")) else "zh-Hans"
    base = lower.replace("_", "-").split("-")[0]
    return base if base in STREETS_LANGS else None


def current_map_language() -> Optional[str]:
    from services.config.job_config import JobConfigManager

    instance = JobConfigManager._instance
    if instance is None or not getattr(instance, "_initialized", False):
        return None
    return streets_lang(instance.get("map_language"))


def raster_style_id(settings: dict, lang: Optional[str], default: str) -> str:
    """Static tiles can't be relabeled, so a locale uses its own Studio style when one is set."""
    if lang:
        localized = settings.get(f"mapbox_style_id_{lang}")
        if localized:
            return localized
    return settings.get("mapbox_style_id", default)


# Runs before mapbox-gl loads: rewrites name_xx lookups in fetched style JSON to the target language
_LOCALIZER_JS = """<script>(function () {
  var FIELD = %s;
  var NAME = /^name_(ar|de|en|es|fr|it|ja|ko|pt|ru|vi|zh-Hans|zh-Hant)$/;
  var STYLE_URL = /\\/styles\\/v1\\/[^/]+\\/[^/?]+(\\?|$)/;
  function localize(e) {
    if (!Array.isArray(e)) return e;
    if (e[0] === "get" && typeof e[1] === "string" && NAME.test(e[1])) return ["get", FIELD];
    return e.map(localize);
  }
  var origFetch = window.fetch;
  window.fetch = function (input, init) {
    var url = typeof input === "string" ? input : (input && input.url) || "";
    var p = origFetch.apply(this, arguments);
    if (!STYLE_URL.test(url)) return p;
    return p.then(function (res) {
      if (!res.ok) return res;
      return res.clone().json().then(function (style) {
        (style.layers || []).forEach(function (l) {
          if (l.type === "symbol" && l.layout && l.layout["text-field"]) {
            l.layout["text-field"] = localize(l.layout["text-field"]);
          }
        });
        return new Response(JSON.stringify(style), {
          status: res.status, statusText: res.statusText, headers: res.headers,
        });
      }).catch(function () { return res; });
    });
  };
})();</script>"""


def style_localizer_script(lang: Optional[str]) -> str:
    return _LOCALIZER_JS % json.dumps(f"name_{lang}") if lang else ""
