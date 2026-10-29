"""Build a short title intro from a random waypoint image (Ken Burns
zoom-in + centered title) — needs only job_config's waypoints, so it has no
dependency on any other step's rendered output.
"""

from pathlib import Path
from typing import List, Optional

from services import tuning, video_text
from services.config.job_config import JobConfigManager

from .helpers import logger, project_attraction_video_dir, project_video_dir


def plan_intro_seconds(settings: dict, cue_times: Optional[dict], audio_seconds: float) -> Optional[float]:
    """How long the intro lasts when the overview voice starts on it: the fade
    from black plus the voice's opening (up to its {start} cue), within
    INTRO_MIN..MAX_SECONDS; the default slideshow length when the script has no
    {start}. None when the voice doesn't start on the intro (setting off, no voice)."""
    if not audio_seconds or not settings.get("overview_voice_over_intro", tuning.DEFAULT_OVERVIEW_VOICE_OVER_INTRO):
        return None
    start = (cue_times or {}).get("start")
    if start is None:
        if intro_style(settings) != "slideshow":
            from services.vdoprocessing.introclip import styled_intro_seconds

            return styled_intro_seconds(intro_style(settings))
        n = tuning.INTRO_IMAGE_COUNT
        return n * tuning.INTRO_PER_IMAGE_SECONDS - (n - 1) * tuning.INTRO_CROSSFADE_SECONDS
    # Ends INTRO_MAP_LEAD_SECONDS before the voice reaches {start}: the map is up before that line begins.
    ends = tuning.INTRO_VOICE_LEAD_SECONDS + float(start) - tuning.INTRO_MAP_LEAD_SECONDS
    seconds = min(tuning.INTRO_MAX_SECONDS, max(tuning.INTRO_MIN_SECONDS, ends))
    # Whole frames: the intro is cut to exactly this, so the overview's cue shift (and its cache key) is stable.
    return round(seconds * tuning.INTRO_FPS) / tuning.INTRO_FPS


def intro_voice_seconds(voice_seconds: float) -> float:
    """The intro's length when the opening narration is its own file: the fade from black, the voice,
    a short breath after it; whole frames, so the overview's cache stays stable."""
    seconds = max(tuning.INTRO_MIN_SECONDS, tuning.INTRO_VOICE_LEAD_SECONDS + voice_seconds + tuning.INTRO_VOICE_TAIL_SECONDS)
    return round(seconds * tuning.INTRO_FPS) / tuning.INTRO_FPS


def place_overview_voice(settings: dict, audio_data: dict, use_cues: bool, render) -> dict:
    """Builds the intro (`render(seconds, cue_times)` -> clip path or None) and places the overview voice:
    the intro's length and scene cues, and the overview's cues and audio length as seen from the overview
    clip's start. The opening as its own file (audio_step.overview_pieces): the intro lasts that voice and
    the overview's voice starts INTRO_MAP_LEAD_SECONDS in, so editing the opening never moves the
    overview; with no intro clip the opening plays at the overview's start and its voice follows. One
    older file: the intro lasts up to the {start} cue and the overview's cues shift back by it
    (`voice_start`: timeline seconds that voice starts at)."""
    overview_cues = audio_data.get("overview_cue_times") if use_cues else None
    overview_audio = audio_data.get("overview_audio_duration") or 0.0
    intro_voice = audio_data.get("intro_voice") if audio_data.get("overview_audio_path") else None
    voice_start, lead = None, 0.0
    if intro_voice:
        intro_seconds = intro_voice_seconds(intro_voice["duration_seconds"])
        intro_cues = intro_voice.get("cue_times") if use_cues else None
        intro_path = render(intro_seconds, intro_cues)
        lead = tuning.INTRO_MAP_LEAD_SECONDS + (0.0 if intro_path else intro_voice["duration_seconds"])
    else:
        intro_seconds = plan_intro_seconds(settings, overview_cues, overview_audio)
        intro_cues = overview_cues  # voice times, before the shift below
        intro_path = render(intro_seconds, intro_cues)
        if intro_path and intro_seconds:
            from services.tts.ttsengine import FFmpegManager

            voice_start = tuning.INTRO_VOICE_LEAD_SECONDS
            try:
                intro_seconds = float(FFmpegManager.get_media_duration(intro_path)) or intro_seconds
            except Exception as exc:  # the planned length is close enough
                logger.warning("Intro: could not probe %s (%s); using the planned length.", intro_path, exc)
            lead = -max(0.0, intro_seconds - voice_start)
    # {scene}/{open}/{close} only time the intro; in the overview's cue list they would re-render it for nothing.
    if overview_cues:
        overview_cues = {
            k: max(0.0, float(v) + lead) for k, v in overview_cues.items()
            if not str(k).startswith(("scene", "photo")) and k not in ("open", "close")
        }
    return {
        "intro_path": intro_path, "intro_seconds": intro_seconds, "intro_cues": intro_cues,
        "intro_voice": intro_voice, "voice_start": voice_start, "overview_lead": max(0.0, lead),
        "overview_cues": overview_cues, "overview_audio": max(0.0, overview_audio + lead) if overview_audio else 0.0,
    }


def intro_style(settings: dict) -> str:
    style = (settings or {}).get("intro_style")
    return style if style in tuning.INTRO_STYLES else tuning.DEFAULT_INTRO_STYLE


def scene_cuts(cue_times: Optional[dict]) -> List[float]:
    """Intro seconds of the opening's {scene} cues (scene2, scene3, ...): the voice starts
    INTRO_VOICE_LEAD_SECONDS into the intro."""
    cuts, n = [], 2
    while f"scene{n}" in (cue_times or {}):
        cuts.append(tuning.INTRO_VOICE_LEAD_SECONDS + float(cue_times[f"scene{n}"]))
        n += 1
    return cuts


def photo_cuts(cue_times: Optional[dict], waypoints: list) -> List[tuple]:
    """[(intro seconds, photo path)] for the opening's {photo:X} cues, in order: X is a stop's name (or part of
    it), its first photo is used. An X matching no stop with a photo is skipped (logged)."""
    cuts = []
    for key, seconds in sorted((cue_times or {}).items(), key=lambda kv: kv[1]):
        if not str(key).startswith("photo") or ":" not in str(key):
            continue
        name = str(key).split(":", 1)[1].strip()
        photo = None
        for exact in (True, False):  # the stop called X, else the first whose name contains X
            for wp in waypoints or []:
                label = str(wp.get("label") or "") if isinstance(wp, dict) else ""
                images = wp.get("popup_image") if isinstance(wp, dict) else None
                images = images if isinstance(images, list) else [images]
                if name and label and (label == name if exact else name in label) and images[0]:
                    photo = images[0]
                    break
            if photo:
                break
        if photo:
            cuts.append((tuning.INTRO_VOICE_LEAD_SECONDS + float(seconds), photo))
        else:
            logger.warning("Intro: {photo:%s} names no stop with a photo — skipped.", name)
    return cuts


def render_intro_clip(
    project_config_path: str, duration_sec: Optional[float] = None, attraction_videos: Optional[List[str]] = None,
    cue_times: Optional[dict] = None,
) -> Optional[str]:
    """Builds the project's intro clip: a randomly-chosen waypoint popup
    image (a fresh pick every call), animated with a gradual zoom-in and
    the project's name burned in, centered. Returns None (never raises) if
    no waypoint has a popup image or generation fails — an intro is
    optional, not something that should hard-fail a pipeline run.
    `duration_sec` fits it to that length (plan_intro_seconds). The text-led
    styles (settings.intro_style) use `attraction_videos` (None: whatever is in
    the project's attraction folder) and cut where the voice says {scene} (`cue_times`)."""
    config_path = Path(project_config_path)
    if not config_path.exists():
        logger.warning("Intro step: no project config found at %s — skipping.", config_path)
        return None

    from services.vdoprocessing.introclip import generate_intro_clip

    job_config = JobConfigManager(config_path)
    if job_config.get("enable_intro") is False:
        logger.info("Intro step: skipped because enable_intro is False.")
        return None

    project_name = job_config.get("project_name", "")
    video_title = job_config.get("video_title")
    if not video_title:
        video_title = project_name
    video_subtitle = job_config.get("video_subtitle", "")

    waypoints = job_config.get("waypoints", [])
    video_dir = project_video_dir(job_config.get("directory_path", config_path.parent))

    logger.info("Intro step: building intro clip for project '%s'.", project_name)
    style = intro_style(job_config.get_settings() or {})
    if style != "slideshow":
        from services.vdoprocessing.introclip import generate_styled_intro

        if attraction_videos is None:
            folder = project_attraction_video_dir(job_config.get("directory_path", config_path.parent))
            attraction_videos = sorted(str(p) for p in folder.glob("04_attraction_*.mp4"))
        return generate_styled_intro(str(video_dir), style, waypoints, attraction_videos, duration_sec=duration_sec,
                                     cuts=scene_cuts(cue_times) if duration_sec else None,
                                     photo_cuts=photo_cuts(cue_times, waypoints) if duration_sec else None)
    # The title and subtitle are a text item on the timeline (intro_text_item), not burned in.
    intro_path = generate_intro_clip(
        video_dir=str(video_dir), title=video_title, subtitle=video_subtitle, waypoints=waypoints,
        burn_text=False, duration_sec=duration_sec,
        photo_cuts=photo_cuts(cue_times, waypoints) if duration_sec else None,
    )

    if intro_path:
        logger.info("Intro step complete: %s", intro_path)
    else:
        logger.info(
            "Intro step: no intro produced (no attraction clips yet, or generation failed)."
        )

    return intro_path


def place_count(waypoints) -> int:
    """Places the walk goes to: every waypoint but unconnected stop-bys."""
    from services.localization.route_brief import on_route

    return sum(1 for w in waypoints or [] if isinstance(w, dict) and on_route(w))


def intro_heading(job_config: JobConfigManager) -> dict:
    """Kicker (settings.intro_location), title and subtitle shared by the intro
    and the outro. The subtitle gets " · N places" (か所 in Japanese) unless settings.intro_place_count
    is false."""
    settings = job_config.get_settings() or {}
    title = job_config.get("video_title") or job_config.get("project_name", "") or ""
    subtitle = (job_config.get("video_subtitle", "") or "").strip()
    n = place_count(job_config.get("waypoints", []))
    if n and settings.get("intro_place_count", tuning.DEFAULT_INTRO_PLACE_COUNT) is not False:
        count = video_text.plural(video_text.current_labels(), "place_count", n, n=n)
        subtitle = tuning.INTRO_PLACE_COUNT_SEPARATOR.join(p for p in (subtitle, count) if p)
    return {
        "kicker": str(settings.get("intro_location") or "").strip(),
        "title": title,
        "subtitle": subtitle,
        "kicker_style": settings.get("intro_kicker_style"),
        "title_style": settings.get("intro_title_style"),
        "subtitle_style": settings.get("intro_subtitle_style"),
    }


def intro_text_item(project_config_path: str) -> Optional[dict]:
    """The intro's kicker + title + subtitle as a text-track item: each line's
    text and its style (settings.intro_*_style). Times are filled in by
    build_timeline, which spans it over the intro clip."""
    config_path = Path(project_config_path)
    if not config_path.exists():
        return None
    h = intro_heading(JobConfigManager(config_path))
    if not (h["title"] or h["subtitle"] or h["kicker"]):
        return None

    def line(which: str) -> dict:
        style = h[f"{which}_style"]
        return {"text": h[which], **({"style": style} if isinstance(style, dict) else {})}

    item = {"kind": "intro", "title": line("title"), "subtitle": line("subtitle")}
    if h["kicker"]:
        item["kicker"] = line("kicker")
    return item


def cued_heading(item: dict, cue_times: Optional[dict]) -> dict:
    """The heading shown from the opening's {open} until its {close} (the voice starts
    INTRO_VOICE_LEAD_SECONDS into the intro); unchanged without them."""
    lead = tuning.INTRO_VOICE_LEAD_SECONDS
    times = {k: round(lead + float(v), 3) for k, v in (cue_times or {}).items() if k in ("open", "close")}
    if not times:
        return item
    item = {**item, "animation": "fade"}
    if "open" in times:
        item["start"] = max(times["open"], float(item.get("start", 0.0)))
    if "close" in times and times["close"] > float(item.get("start", 0.0)):
        item["end"] = min(times["close"], float(item.get("end", times["close"])))
    return item


def intro_text_items(
    project_config_path: str, use_llm: bool = True, duration_sec: Optional[float] = None, cue_times: Optional[dict] = None,
) -> List[dict]:
    """The intro's text-track items: the heading (intro_text_item) for the slideshow; for a text-led
    style one item per scene with its line (intro_lines) and look (INTRO_STYLE_SCENES[...]["text"]),
    timed inside its scene."""
    config_path = Path(project_config_path)
    if not config_path.exists():
        return []
    job_config = JobConfigManager(config_path)
    style = intro_style(job_config.get_settings() or {})
    if style == "slideshow":
        item = intro_text_item(project_config_path)
        return [cued_heading(item, cue_times)] if item else []

    from services.localization.intro_lines import intro_lines
    from services.localization.script_engine import script_generator
    from services.vdoprocessing.introclip import scene_starts, styled_scenes

    project = {k: job_config.get(k) for k in ("settings", "video_title", "project_name", "waypoints")}
    generate = script_generator(project["settings"])[0] if use_llm else None
    lines = intro_lines(project, job_config.get("directory_path", config_path.parent), video_text.current_language(), generate)
    if generate is not None:
        from services.ollama_memory import unload_ollama_models

        unload_ollama_models()  # silent when Ollama isn't running
    scenes = styled_scenes(style, duration_sec, scene_cuts(cue_times) if duration_sec else None)  # as rendered
    cf, inset = tuning.INTRO_CROSSFADE_SECONDS, tuning.INTRO_LINE_INSET_SECONDS
    heading = intro_heading(job_config)
    poetic = iter(lines)
    items = []
    for i, (scene, start) in enumerate(zip(scenes, scene_starts([s["seconds"] for s in scenes], cf))):
        look = scene["text"]
        if scene.get("title"):
            # The route's name: location kicker, title, subtitle, each line as the editor styles it.
            texts = {"kicker": heading["kicker"], "title": heading["title"], "subtitle": heading["subtitle"]}
            styles = {"kicker": look["kicker"], "title": look["style"], "subtitle": look["subtitle"]}
        else:
            texts, styles = {"title": next(poetic, ""), "subtitle": ""}, {"title": look["style"]}
        if not any(texts.values()):
            continue
        end = start + scene["seconds"] - (cf / 2 if i < len(scenes) - 1 else tuning.INTRO_FADE_SECONDS)
        item = {
            "start": round(start + (inset if i else tuning.INTRO_FADE_SECONDS), 3), "end": round(end - inset, 3),
            "kind": "intro", "animation": "fade",
            **{k: v for k, v in look.items() if k not in ("style", "kicker", "subtitle")},
        }
        for which, text in texts.items():
            if text or which != "kicker":
                item[which] = {"text": text, **({"style": dict(styles[which])} if which in styles else {})}
        # {open}/{close} time the text of the scene they fall in.
        marks = [tuning.INTRO_VOICE_LEAD_SECONDS + float(v) for k, v in (cue_times or {}).items() if k in ("open", "close")]
        timed = any(start <= t < start + scene["seconds"] for t in marks)
        items.append(cued_heading(item, cue_times) if timed else item)
    return items
