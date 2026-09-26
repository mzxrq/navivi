"""Overview narration drafting: a tour-guide script built from the route itself
(services/localization/overview_script.build_tour_script)."""

import json
from pathlib import Path
from typing import Any, Dict

from services.localization.cues import clean_text

DEFAULT_SCRIPT_MODEL = "schroneko/gemma-2-2b-jpn-it"
DRAFT_NAME = "overview_script_draft.txt"


def test_overview_script(job_config_path: str, use_llm: bool = True) -> Dict[str, Any]:
    """Drafts the overview narration: the way between stops told from the
    route, each stop described from its own narration, with {start} / {n} /
    {go} / {end} cues so the overview stops while a place is described. The
    draft is written beside job_config.json (never over overview_narration);
    `use_llm=False` builds it from the facts alone, with no model."""
    from services.localization.overview_script import (
        build_tour_script, in_overview_range, ollama_generate, plan_budget,
    )
    from services.localization.route_brief import build_brief

    config_path = Path(job_config_path)
    project = json.loads(config_path.read_text(encoding="utf-8"))
    try:
        cache = json.loads((config_path.parent / ".routecache.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        cache = {}
    model = project.get("settings", {}).get("overview_script_model", DEFAULT_SCRIPT_MODEL)
    generate = ollama_generate(model) if use_llm else None
    script, report = build_tour_script(project, cache, generate)
    draft = config_path.parent / DRAFT_NAME
    draft.write_text(script, encoding="utf-8")
    budget = plan_budget(project, build_brief(project, cache))
    spoken = len(clean_text(script))
    estimated = spoken / budget["cps"]
    return {
        "success": True,
        "script": script,
        "draft_path": str(draft),
        "model": model if use_llm else None,
        "spoken_chars": spoken,
        # The overview aims at target_seconds and must stay within 60-90s;
        # checked again on the real audio after TTS.
        "target_seconds": round(budget["target"], 1),
        "estimated_seconds": round(estimated, 1),
        "within_60_90s": in_overview_range(estimated),
        # the numbered stops the walker stops at; the others are passed
        "stopped_at": budget["stops"],
        "pieces": [{k: r[k] for k in ("kind", "used", "budget_chars", "text")} for r in report],
    }
