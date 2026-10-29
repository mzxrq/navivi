"""Step 4's RouteAnimator config: every render setting, read from the project's settings with their defaults."""

from services import tuning
from services.localization.cues import tags_at_sentence_start
from services.localization.overview_script import overview_style

from .audio_step import overview_tagged_script
from .helpers import attraction_videos_enabled
from .overview_framing import _course_config
from .render_look import _arrived_marker_color, _mode_line_color_overrides, _project_color, look_options


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
    use_3d_res,
    use_pydeck_pedestrian,
):
    """The config dict RouteAnimator renders the overview and the legs with."""
    animator_config = {
        "output_dir": output_video_dir,
        # Gates the per-leg/per-clip "file already exists, skip it" checks
        # in overview.py/route2vdo.py/waypoints.py — only a real
        # run_full_pipeline render (render_mode == "both") should ever
        # resume from partial output like this. A standalone
        # render_mode="overview"/"residential" call (services/cli/
        # gps_commands.py's test_overview_video/test_residential_video —
        # the map editor's own "recreate this video" actions) exists
        # specifically so a user can force ONE piece to redo; honoring
        # leftover files from a previous run there would silently no-op
        # the very action they asked for, exactly the bug this function's
        # own manifest checkpoint above already had to be fixed for.
        # --force redoes every clip, so no per-file "already exists" skipping either.
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
        # A connected stop-by's fullscreen photo does the same (no hold, no
        # blur-out) when an attraction video follows it.
        "dissolve_into_attraction": (
            attraction_videos_enabled(settings)
            and float(settings.get("attraction_fade_seconds", 0.8)) > 0
        ),
        "use_3d_res": use_3d_res,
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
        "overview_cue_wait_seconds": float(settings.get("overview_cue_wait_seconds", 2.0)),
        # The overview video type (each with its own script); "course" also
        # cycles headline taglines taken from the route (overview_script.course_taglines).
        "overview_style": overview_style(project_config),
        **_course_config(project_config, config_path),
        "res_route_path": project_config_path,
        "leg_durations": seg_durations or None,
        "duration": settings.get("duration", overview_duration),
        **{
            k: settings.get(k, default)
            for k, default in [
                ("fps", 30),
                ("line_thickness", 10),
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
        # Colors: authored RGB in job_config.json, drawn BGR — see
        # _project_color. The defaults passed here are already BGR.
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
        # Pin colors by role. Unset keys fall through to the defaults on
        # SpatialRendererBase (start/end/drawn/stop-by) — a project only
        # needs to name the ones it actually wants to change.
        "start_pin_color": _project_color(settings, "start_pin_color", tuning.START_PIN_COLOR),
        "end_pin_color": _project_color(settings, "end_pin_color", tuning.END_PIN_COLOR),
        "drawn_pin_color": _project_color(settings, "drawn_pin_color", tuning.DRAWN_PIN_COLOR),
        "stopby_pin_color": _project_color(settings, "stopby_pin_color", tuning.STOPBY_PIN_COLOR),
        "trigger_radius_padding": settings.get("trigger_radius_padding", {}),
        "route_marker": route_marker,
        "marker_base_dir": marker_base_dir,
        **look_options(settings),
        "fullscreen_transition": settings.get("fullscreen_transition", {}),
        # Real-world average speed (km/h) per travel mode — how much
        # faster a car/ferry/etc. leg animates on screen relative to a
        # walking one is derived from these ratios (see SpatialRenderer's
        # _DEFAULT_MODE_SPEED_KMH for the fallback values). Set e.g.
        # {"walking": 3, "car": 70, "ferry": 36} in job_config.json's
        # settings to override per project.
        "mode_speeds_kmh": settings.get("mode_speeds_kmh", {}),
        "animation_speeds_kmh": settings.get("animation_speeds_kmh", {}),
        # Which summary-card template the overview/per-leg cards render as
        # ("glass" default, or "taskbar" for the notification-flyout-style
        # template — see cards.py's render_summary_card). Was missing from
        # this dict entirely, so job_config.json's settings.summary_card_style
        # never reached RouteAnimator/GraphicsEngine no matter what a
        # project set it to — self.config here IS this whole dict, not the
        # raw settings (see RouteAnimator.__init__'s own note on that).
        "summary_card_style": settings.get(
            "summary_card_style", tuning.DEFAULT_SUMMARY_CARD_STYLE
        ),
        # Per-project override of any subset of assets/config/labels_ja.json's
        # summary-card keys (mode_name, mode_duration_label, total_label,
        # distance_label, taskbar_card_title) — see cards.py's
        # merge_summary_card_labels. Same "must be forwarded through THIS
        # dict, not just read off raw settings" requirement as
        # summary_card_style above.
        "summary_card_labels": settings.get("summary_card_labels"),
        # HUD/card theme: settings.theme or top-level theme ("light"/"dark").
        "theme": tuning.resolve_ui_theme(project_config),
        # Legs keep their path above a band sized to the project's caption.
        "caption_style": settings.get("caption_style"),
    }
    return animator_config
