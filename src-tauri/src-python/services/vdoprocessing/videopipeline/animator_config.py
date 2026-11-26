"""Step 4's RouteAnimator config: every render setting, read from the project's settings with their defaults."""

from services import tuning
from services.localization.cues import tags_at_sentence_start
from services.localization.overview_script import overview_style
from services.vdoprocessing.storyboard import of as storyboard_of

from .audio_step import overview_tagged_script
from .helpers import attraction_videos_enabled
from .overview_framing import _course_config
from .render_look import _arrived_marker_color, _mode_line_color_overrides, _project_color, look_options


def _run_options(
    *, config_path, force, is_full_pipeline_render, output_video_dir, overview_audio_duration,
    overview_cue_times, overview_stale, project_config, settings, use_pydeck_pedestrian,
) -> dict:
    """The part of the config that says how this run plays: resume checks, transitions, narration cues."""
    return {
        "output_dir": output_video_dir,
        # Gates the per-leg/per-clip "file already exists, skip it" checks in overview.py/route2vdo.py/
        # waypoints.py — only a real run_full_pipeline render (render_mode == "both") may resume from partial
        # output. A standalone render_mode="overview"/"residential" call (the map editor's "recreate this
        # video" actions) exists so a user can force ONE piece to redo; leftover files there would silently
        # no-op it. --force redoes every clip, so no "already exists" skipping either.
        "checkpoint_enabled": is_full_pipeline_render and not force,
        # Inputs changed since the last render: the existing overview is stale.
        "overview_rerender": overview_stale,
        "min_free_ram_gb": settings.get("min_free_ram_gb"),
        "enable_attraction_videos": attraction_videos_enabled(settings),
        # The at-arrival photo grows to fullscreen and the clip ends right
        # there - no hold. The dissolve into the attraction video that follows
        # runs on extra frames added at export (VideoExporter._crossfade_pair),
        # so it starts the moment the photo is fullscreen.
        "arrival_photo_hold_seconds": 0.0,
        # At a stop with no attraction script: "slide" (the walk goes on, its photo card rides along) or "zoom".
        "quiet_stop_transition": settings.get("quiet_stop_transition", "slide"),
        # A connected stop-by's fullscreen photo does the same (no hold, no
        # blur-out) when an attraction video follows it.
        "dissolve_into_attraction": (
            attraction_videos_enabled(settings)
            and float(settings.get("attraction_fade_seconds", 0.8)) > 0
        ),
        "use_pydeck_pedestrian": use_pydeck_pedestrian,
        "use_pydeck_overview": bool(settings.get("use_pydeck_overview", tuning.DEFAULT_USE_PYDECK_OVERVIEW)),
        "mapbox_style_id": settings.get("mapbox_style_id"),
        # Where the narration's cues fall: the overview reaches each cued stop
        # then (spatial_renderer/overview.py).
        "overview_cue_seconds": dict(overview_cue_times or {}),
        # The narration's length: with cues, the overview's ending is fitted
        # so the video ends with the voice.
        "overview_audio_seconds": float(overview_audio_duration or 0.0),
        # A cue at the start of a sentence: the voice starts talking about that
        # stop at the cue, so the walker waits there a moment (this many seconds)
        # to stay in step with it.
        "overview_cue_wait_tags": tags_at_sentence_start(
            overview_tagged_script(project_config, config_path.parent)
        ),
        "overview_cue_wait_seconds": float(settings.get(
            "overview_cue_wait_seconds", storyboard_of(overview_style(project_config)).timings["cue_wait_seconds"]
        )),
        # The overview video type (each with its own script).
        "overview_style": overview_style(project_config),
        "overview_cards_stay": settings.get("overview_cards_stay", True),
    }


def summary_card_style(settings: dict) -> str:
    """The totals card's design: the theme's, else the project's summary_card_style, else the default."""
    theme = tuning.overview_theme(settings.get("overview_theme"))
    return theme.get("card_style") or settings.get("summary_card_style") or tuning.DEFAULT_SUMMARY_CARD_STYLE


def _color_options(settings: dict, marker_color_bgr) -> dict:
    """Colors: authored RGB in job_config.json, drawn BGR — see _project_color. The defaults passed here are
    already BGR. Pin colors by role: unset keys fall through to the defaults on SpatialRendererBase
    (start/end/drawn/stop-by), so a project only names the ones it wants to change."""
    return {
        "line_color": _project_color(settings, "line_color", (243, 150, 33)),
        "mode_line_colors": _mode_line_color_overrides(settings),
        "marker_color": marker_color_bgr,
        "arrived_marker_color": _arrived_marker_color(settings, marker_color_bgr),
        "card_border_color": _project_color(
            settings, "card_border_color", tuning.DEFAULT_CARD_BORDER_COLOR
        ),
        "route_line_border_color": _project_color(
            settings, "route_line_border_color", tuning.DEFAULT_LINE_BORDER_COLOR
        ),
        "start_pin_color": _project_color(settings, "start_pin_color", tuning.START_PIN_COLOR),
        "end_pin_color": _project_color(settings, "end_pin_color", tuning.END_PIN_COLOR),
        "drawn_pin_color": _project_color(settings, "drawn_pin_color", tuning.DRAWN_PIN_COLOR),
        "stopby_pin_color": _project_color(settings, "stopby_pin_color", tuning.STOPBY_PIN_COLOR),
    }


def build_animator_config(
    *,
    config_path,
    force,
    is_full_pipeline_render,
    marker_base_dir,
    marker_color_bgr,
    output_video_dir,
    overview_audio_duration,
    overview_cue_times,
    overview_duration,
    overview_stale,
    project_config,
    project_config_path,
    route_marker,
    seg_durations,
    settings,
    use_pydeck_pedestrian,
):
    """The config dict RouteAnimator renders the overview and the legs with."""
    animator_config = {
        **_run_options(
            config_path=config_path, force=force, is_full_pipeline_render=is_full_pipeline_render,
            output_video_dir=output_video_dir, overview_audio_duration=overview_audio_duration,
            overview_cue_times=overview_cue_times, overview_stale=overview_stale,
            project_config=project_config, settings=settings, use_pydeck_pedestrian=use_pydeck_pedestrian,
        ),
        **_course_config(project_config, config_path),
        "res_route_path": project_config_path,
        "leg_durations": seg_durations or None,
        "duration": settings.get("duration", overview_duration),
        **{
            k: settings.get(k, default)
            for k, default in [
                ("fps", 30),
                ("line_thickness", 7),
                ("marker_radius", 16),
                ("map_font_size", 24),
                ("card_border_thickness", tuning.DEFAULT_CARD_BORDER_THICKNESS),
                ("route_line_border_thickness", tuning.DEFAULT_LINE_BORDER_THICKNESS),
                ("pause", 2.0),
                ("summary_hold", 4.0),
                ("summary_fade", 0.5),
                ("clip_summary_hold", 2.0),
                ("show_segment_summary", True),
                ("res_duration", 12.0),
                ("post_arrival_hold_seconds", 1.0),
                ("default_transition_hold_seconds", 1.5),
                ("hide_route_on_popup", False),
                ("enable_fullscreen_popups", True),
                ("hide_upcoming_pins_on_popup", False),
            ]
        },
        **_color_options(settings, marker_color_bgr),
        "trigger_radius_padding": settings.get("trigger_radius_padding", {}),
        "route_marker": route_marker,
        "marker_base_dir": marker_base_dir,
        **look_options(settings),
        "fullscreen_transition": settings.get("fullscreen_transition", {}),
        # Real-world average speed (km/h) per travel mode — how much faster a car/ferry/etc. leg animates on
        # screen relative to a walking one is derived from these ratios (SpatialRenderer's
        # _DEFAULT_MODE_SPEED_KMH holds the fallbacks), e.g. {"walking": 3, "car": 70, "ferry": 36}.
        "mode_speeds_kmh": settings.get("mode_speeds_kmh", {}),
        "animation_speeds_kmh": settings.get("animation_speeds_kmh", {}),
        # Summary-card template ("glass" default, or "taskbar", see cards.py's render_summary_card) and
        # per-project label overrides (cards.py's merge_summary_card_labels). They must be forwarded through
        # THIS dict: self.config in RouteAnimator is this whole dict, not the raw settings.
        # shortcut: legs draw their card from this too; give them their own when a second theme exists.
        "summary_card_style": summary_card_style(settings),
        "overview_theme": settings.get("overview_theme", "current"),
        "summary_card_labels": settings.get("summary_card_labels"),
        # HUD/card theme: settings.theme or top-level theme ("light"/"dark").
        "theme": tuning.resolve_ui_theme(project_config),
        # Legs keep their path above a band sized to the project's caption.
        "caption_style": settings.get("caption_style"),
    }
    return animator_config
