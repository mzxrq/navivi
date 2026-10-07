"""Overview narration drafting: a tour-guide script built from the route itself
(services/localization/overview_script.build_tour_script)."""

import json
from pathlib import Path
from typing import Any, Dict

from services.localization.cues import clean_text

DRAFT_NAME = "overview_script_draft.txt"


def _length_report(project: Dict[str, Any], cache: Dict[str, Any], script: str) -> Dict[str, Any]:
    """How long `script` is when spoken, against what the overview aims at.
    The voice's speed is the project's own (plan_budget), so the editor can
    re-time a hand edit from `chars_per_second` without another call."""
    from services.localization.overview_script import (
        TARGET_MAX_SECONDS, TARGET_MIN_SECONDS, in_overview_range, plan_budget,
    )
    from services.localization.route_brief import build_brief

    budget = plan_budget(project, build_brief(project, cache))
    spoken = len(clean_text(script))
    estimated = spoken / budget["cps"]
    return {
        "spoken_chars": spoken,
        "chars_per_second": round(budget["cps"], 3),
        # The overview aims at target_seconds and should stay within 60-120s
        # (overview_script.TARGET_MIN/MAX_SECONDS, give or take the 3s the
        # video absorbs); checked again on the real audio after TTS.
        "target_seconds": round(budget["target"], 1),
        "estimated_seconds": round(estimated, 1),
        "within_60_90s": in_overview_range(estimated),
        "min_seconds": TARGET_MIN_SECONDS,
        "max_seconds": TARGET_MAX_SECONDS,
        # the numbered stops the walker stops at; the others are passed
        "stopped_at": budget["stops"],
    }


def _load_project(job_config_path: str):
    from services.projectfiles import ROUTE_CACHE, meta_file

    config_path = Path(job_config_path)
    project = json.loads(config_path.read_text(encoding="utf-8"))
    try:
        cache = json.loads(meta_file(config_path.parent, ROUTE_CACHE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    return config_path, project, cache


def test_overview_script(job_config_path: str, use_llm: bool = True) -> Dict[str, Any]:
    """Drafts the overview narration: the way between stops told from the
    route, each stop described from its own narration, with {start} / {n} /
    {go} / {end} cues so the overview stops while a place is described. The
    draft is written beside job_config.json (never over overview_narration:
    the editor decides whether to take it); `use_llm=False` builds it from the
    facts alone, with no model. `source_ids` is what narration_step stores as
    overview_narration_source_ids for an auto script: the editor keeps it so
    the pipeline can tell when the stops changed since."""
    from services.localization.overview_script import build_tour_script
    from services.localization.script_engine import script_generator
    from services.vdoprocessing.videopipeline.narration_step import _overview_source_ids

    config_path, project, cache = _load_project(job_config_path)
    generate, model = script_generator(project.get("settings", {})) if use_llm else (None, None)
    script, report = build_tour_script(project, cache, generate)
    draft = config_path.parent / DRAFT_NAME
    draft.write_text(script, encoding="utf-8")
    return {
        "success": True,
        "script": script,
        "draft_path": str(draft),
        "model": model if use_llm else None,
        "source_ids": _overview_source_ids(project),
        **_length_report(project, cache, script),
        "pieces": [{k: r[k] for k in ("kind", "used", "budget_chars", "text")} for r in report],
    }


def overview_length(job_config_path: str, text: str) -> Dict[str, Any]:
    """The length report for a script the user typed (no model, no files
    written): lets the editor show "about 74 s of 60-120 s" for a hand edit."""
    _config_path, project, cache = _load_project(job_config_path)
    return {"success": True, **_length_report(project, cache, text)}
