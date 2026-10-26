"""The two on-screen lines of a text-led intro (settings.intro_style "cinematic" / "documentary").

The user's settings.intro_lines win. Otherwise the project's script model writes them once, cached in
.navivi/intro_lines.json against the inputs so a rerender keeps the same lines; with no model (or a
bad answer) a fixed template is used.
"""

import json
import re
from pathlib import Path
from typing import Callable, List, Optional

from services.logger.logger import setup_logger
from services.projectfiles import meta_dir, meta_path, write_json_atomic

logger = setup_logger("IntroLines")

Generate = Callable[[str, int], Optional[str]]

_LIMIT = {"ja": 22, "en": 56}


def _template(lang: str, area: str) -> List[str]:
    if lang == "ja":
        return ["日常の扉をそっと閉じ、", f"{area}、歴史の鼓動に耳を澄ませる旅へ――。" if area else "歴史の鼓動に耳を澄ませる旅へ――。"]
    return ["Gently closing the door on everyday life,", f"we set out to hear the heartbeat of {area}." if area else "we set out to hear the heartbeat of history."]


def _prompt(lang: str, area: str, title: str, stops: List[str], limit: int) -> str:
    if lang == "ja":
        return (
            "旅番組の冒頭に、映像の上へ静かに表示する2行の詩的な言葉を書きます。\n"
            + (f"■ 地域: {area}\n" if area else "")
            + (f"■ 題名: {title}\n" if title else "")
            + (f"■ 巡る場所: {'、'.join(stops)}\n" if stops else "")
            + f"■ 条件: 2行。1行目は日常から離れる静かな書き出し（読点で終える）、2行目は旅へ誘う結び。各行{limit}文字以内。"
            "上の情報にない地名・数字は書かない。番号・括弧・英語は使わず、2行の本文のみを出力。"
        )
    return (
        "Write two short poetic lines shown quietly over the opening shots of a travel video.\n"
        + (f"Area: {area}\n" if area else "")
        + (f"Title: {title}\n" if title else "")
        + (f"Places: {', '.join(stops)}\n" if stops else "")
        + f"Rules: two lines; the first opens a quiet thought (ends with a comma), the second invites the journey. "
        f"Each at most {limit} characters. No place names or numbers not given above. No numbering or quotes. Output only the two lines."
    )


def parse_lines(raw: Optional[str], limit: int) -> Optional[List[str]]:
    """The model's two lines, cleaned; None when the answer isn't two short lines."""
    if not raw:
        return None
    lines = [re.sub(r"^\s*(?:\d+[.)、]|[-*・])\s*", "", line).strip().strip("「」『』\"'“”") for line in raw.splitlines()]
    lines = [line for line in lines if line]
    if len(lines) < 2:
        return None
    lines = lines[:2]
    if any(len(line) < 3 or len(line) > limit * 1.3 or re.search(r"[{}<>\\]", line) for line in lines):
        return None
    return lines


def intro_lines(project: dict, project_dir, lang: str, generate: Optional[Generate] = None) -> List[str]:
    settings = project.get("settings") or {}
    typed = [str(x or "").strip() for x in (settings.get("intro_lines") or [])][:2]
    area = str(settings.get("intro_location") or "").strip()
    if any(typed):
        template = _template(lang, area)
        return [t or template[i] for i, t in enumerate(typed + [""] * (2 - len(typed)))]

    from services.localization.overview_script import visible_waypoints

    title = str(project.get("video_title") or project.get("project_name") or "").strip()
    stops = [n for n in ((w.get("label") or w.get("name") or "").strip() for w in visible_waypoints(project)) if n][:6]
    key = [lang, area, title, stops]
    cache = meta_dir(project_dir) / "intro_lines.json"
    try:
        saved = json.loads(Path(cache).read_text(encoding="utf-8"))
        if saved.get("key") == key and isinstance(saved.get("lines"), list) and len(saved["lines"]) == 2:
            return saved["lines"]
    except (OSError, ValueError, AttributeError):
        pass

    limit = _LIMIT.get(lang, _LIMIT["en"])
    lines = None
    if generate is not None:
        try:
            lines = parse_lines(generate(_prompt(lang, area, title, stops, limit), limit * 2), limit)
        except Exception as exc:  # no model running: the template is fine
            logger.warning("Intro lines: model failed (%s); using the template.", exc)
    if lines is None:
        return _template(lang, area)
    try:
        write_json_atomic(meta_path(project_dir, ("intro_lines.json",)), {"key": key, "lines": lines})
    except OSError as exc:
        logger.warning("Intro lines: could not cache (%s).", exc)
    return lines
