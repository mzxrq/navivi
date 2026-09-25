"""
Route to Video Animator (route2vdo.py)
---------------------------------------------------------------------------
Main Orchestrator. Parses CLI arguments and JSON data, then routes
the drawing commands to either the Spatial or Storyboard renderers.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from services.mapfetcher.graphicengine import GraphicsEngine
from services.logger.logger import setup_logger
from services.logger.progress import tracker
from services import tuning
from services.vdoprocessing.spatial_renderer import SpatialRenderer
from services.vdoprocessing.pydeckrecorder import record_headless_video

# Logging configuration
logger = setup_logger("RouteAnimator")

# Shared fallback defaults — reused both as the initial GraphicsEngine
# config value and later as the CLI --thickness/--radius/--summary-hold
# fallback when neither the CLI flag nor the route JSON's settings supply
# one. Named here so both use sites can't silently drift apart.
DEFAULT_LINE_THICKNESS = 10
DEFAULT_MARKER_RADIUS = 24
DEFAULT_SUMMARY_HOLD_SECONDS = 4.0


def _output_is_valid(path, min_bytes: int = 1024) -> bool:
    """Checkpoint helper — see spatial_renderer/overview.py's identical
    copy for why this is duplicated instead of imported from
    videopipeline/helpers.py (circular import)."""
    try:
        p = Path(path)
        return p.is_file() and p.stat().st_size >= min_bytes
    except OSError:
        return False


class RouteAnimator:
    """Orchestrates the animation pipeline by bridging configurations with Renderers."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

        # NOTE: `self.config` here is already the flattened settings dict
        # render_route_video builds (animator_config) — it has no nested
        # "settings" key of its own, so a `self.config.get("settings", {})`
        # lookup (the old code) always fell through to `{}` and silently
        # discarded whatever settings.map_font_size/card_border_* a project
        # actually configured. Read the keys directly off self.config.
        map_font_size = self.config.get("map_font_size", 24) if self.config else 24

        # 1. Initialize the Core Graphics Engine
        self.graphics = GraphicsEngine(
            line_color=self.config.get("line_color", (243, 150, 33)),  # BGR blue
            line_thickness=self.config.get("line_thickness", DEFAULT_LINE_THICKNESS),
            # Was hardcoded to (0, 0, 255)/(0, 0, 220) here — both pure red
            # in BGR — completely independent of (and inconsistent with)
            # tuning.DEFAULT_MARKER_COLOR's own blue default. Since a
            # project's job_config.json rarely sets "marker_color"
            # explicitly, every not-yet-arrived numbered pin (and every
            # popup card border, which falls back to this same color —
            # see pins.py's _pin_color/_pin_label_and_color) rendered red
            # instead of the intended blue in every real render. Falling
            # back to the SAME tuning.py defaults GraphicsEngineBase
            # itself already uses keeps this consistent regardless of
            # which one actually ends up supplying the color.
            marker_color=self.config.get("marker_color", tuning.DEFAULT_MARKER_COLOR),
            arrived_marker_color=self.config.get(
                "arrived_marker_color", tuning.DEFAULT_ARRIVED_MARKER_COLOR
            ),
            marker_radius=self.config.get("marker_radius", DEFAULT_MARKER_RADIUS),
            font_size=map_font_size,
            card_border_color=tuple(
                self.config.get("card_border_color", tuning.DEFAULT_CARD_BORDER_COLOR)
            ),
            card_border_thickness=self.config.get(
                "card_border_thickness", tuning.DEFAULT_CARD_BORDER_THICKNESS
            ),
            line_border_color=tuple(
                self.config.get("route_line_border_color", tuning.DEFAULT_LINE_BORDER_COLOR)
            ),
            line_border_thickness=self.config.get(
                "route_line_border_thickness", tuning.DEFAULT_LINE_BORDER_THICKNESS
            ),
            summary_card_style=self.config.get(
                "summary_card_style", tuning.DEFAULT_SUMMARY_CARD_STYLE
            ),
            summary_card_labels=self.config.get("summary_card_labels"),
            # Per-mode line colors: the pipeline puts {"walking": <the
            # project's own Route Line color>} here when the project
            # picked one, so the ordinary leg follows the map-appearance
            # panel instead of tuning.py's walking blue — see
            # render_step.py's _mode_line_color_overrides.
            mode_line_colors=self.config.get("mode_line_colors"),
        )

        self.out_dir = Path(config.get("output_dir", ""))
        self.out_dir.mkdir(parents=True, exist_ok=True)

        # 2. Initialize the isolated Render Engines
        self.spatial_renderer = SpatialRenderer(
            self.config, self.graphics, self.out_dir
        )

    def load_route_data(self, json_path: str) -> Tuple[List, List, List, Dict]:
        """Loads and parses the waypoints into memory."""
        with open(json_path, "r", encoding="utf-8") as f:
            raw_data = json.load(f)

        if isinstance(raw_data, list):
            route_data, settings = raw_data, {}
        else:
            route_data = raw_data.get("route", raw_data.get("points", []))
            settings = raw_data.get("settings", {})

        points, labels, popups = [], [], []
        for item in route_data:
            if isinstance(item, (list, tuple)):
                points.append([float(item[0]), float(item[1])])
                labels.append(None)
                popups.append(None)
            elif isinstance(item, dict):
                points.append([float(item["x"]), float(item["y"])])
                labels.append(item.get("label"))
                # ADDED: Check for 'transition' key in the JSON configuration
                if (
                    "freeze_seconds" in item
                    or "popup_image" in item
                    or "popup_video" in item
                    or "transition" in item
                ):
                    popups.append(
                        {
                            "freeze_seconds": min(
                                float(item.get("freeze_seconds", 2.0)),
                                tuning.POPUP_FREEZE_SECONDS_MAX,
                            ),
                            "popup_image": item.get("popup_image"),
                            "popup_video": item.get("popup_video"),
                            "image_display": item.get(
                                "image_display", item.get("image display", "box")
                            ),
                            # ADDED: Store the transition type (e.g., 'pop up', 'fullscreen')
                            "transition": item.get("transition", "popup"),
                            "triggered": False,
                        }
                    )
                else:
                    popups.append(None)
            else:
                raise ValueError(f"Unknown point format: {item}")

        return points, labels, popups, settings

    def _freeze_video_end(self, video_path: str, hold_seconds: float):
        """Uses FFmpeg tpad filter to seamlessly clone and hold the final frame."""
        if hold_seconds <= 0:
            return

        logger.info(
            f"❄️ Freezing the final overview frame for {hold_seconds} seconds..."
        )
        temp_out = str(
            Path(video_path).with_name(f"temp_frozen_{Path(video_path).name}")
        )

        # [HACK] [Editor] FFmpeg has no native "hold last frame" operation on
        # an already-encoded clip, so tpad's clone mode re-encodes the whole
        # file just to duplicate the final frame for hold_seconds.
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vf",
            f"tpad=stop_mode=clone:stop_duration={hold_seconds}",
            "-c:v",
            "libx264",
            *tuning.ffmpeg_thread_args(),
            "-pix_fmt",
            "yuv420p",
            temp_out,
        ]

        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if result.returncode == 0 and os.path.exists(temp_out):
            os.replace(temp_out, video_path)
        else:
            logger.warning("Failed to freeze video end. Skipping freeze frame.")

    def _render_overview_pydeck(
        self, img_path: str, points: List, labels: List, popups: List,
        extent: Optional[Tuple[float, float, float, float]], fps: int,
    ) -> Optional[str]:
        """GeoJsonLayer-driven alternative to SpatialRenderer.render_overview
        — a static overview image (full route + numbered pins) instead of
        an animated OpenCV line-draw. `points` are still in the PIXEL space
        of `img_path` (see load_route_data/_project_route_to_pixels
        upstream); reprojected back to lat/lon via `extent`, same mechanism
        overview.py's own `_route_latlon_path` already relies on — this
        module never needed its own fetched background raster to begin
        with, only real coordinates to hand to a live pydeck/Mapbox basemap.
        """
        if extent is None:
            logger.warning(
                "use_pydeck_pedestrian overview requested but no extent was "
                "supplied — cannot reproject pixel points to lat/lon. "
                "Skipping overview render."
            )
            return None

        from services.mapfetcher.mapgeometry import RouteGeometryProcessor
        from services.vdoprocessing.pydeckrecorder.pedestrian import render_overview_video_pydeck

        bg = self.graphics.read_image_safe(str(img_path))
        if bg is None:
            raise FileNotFoundError(f"Cannot read background image: {img_path}")
        h, w = bg.shape[:2]

        route_latlon = [
            RouteGeometryProcessor.pixel_to_latlon(p[0], p[1], extent, w, h) for p in points
        ]

        waypoints = []
        order = 0
        for i, popup in enumerate(popups):
            if popup is None:
                continue
            is_stopby = bool(popup.get("is_stopby"))
            lat, lon = RouteGeometryProcessor.pixel_to_latlon(points[i][0], points[i][1], extent, w, h)
            # A stop-by isn't part of the visible 1..N numbering (see
            # _pin_layers/overview.py's own matching rule) — order still
            # gets set (as the pre-increment count) so it's never missing,
            # just not incremented for it.
            entry = {"lat": lat, "lon": lon, "order": order, "label": labels[i], "is_stopby": is_stopby}
            if not is_stopby:
                order += 1
                entry["order"] = order
            waypoints.append(entry)

        # The reference video's wide section-title caption (e.g.
        # "友ヶ島・加太をめぐる道") reads as the trip's own name — reusing
        # job_config.json's project_name is the closest real data source
        # for that, same file _get_job_config already walks up to find.
        job_config = self.spatial_renderer._get_job_config() or {}
        title_text = self.config.get("overview_title") or job_config.get("project_name")

        output_path = str(self.out_dir / "01_overview.mp4")
        if self.config.get("checkpoint_enabled", False) and _output_is_valid(output_path):
            logger.info("Overview video already exists — skipping render: %s", output_path)
            return output_path
        duration = self.config.get("duration", 30.0)
        return render_overview_video_pydeck(
            route_latlon, waypoints, output_path, duration=duration, fps=fps, title_text=title_text,
        )

    def _render_residential_pydeck(self, res_sequence: List[Dict], fps: int) -> List[str]:
        """GeoJsonLayer-driven alternative to both SpatialRenderer.
        render_waypoints (flat top-down) and the 3D driving pipeline's
        record_headless_video (vehicle-scenegraph chase cam): a pedestrian-
        scale chase camera with a turn-by-turn HUD, one clip per leg.

        Reuses each res_sequence entry's own real `lats`/`lons` arrays
        (already resolved by render_step.py — including ferry-leg cached
        geometry and stop-by-merged legs — no pixel reprojection needed
        here, unlike the overview path) and mirrors waypoints.py's own
        `02_waypoint_{start_pos+1:02d}_{safe_suffix}.mp4` filename
        convention so downstream audio-muxing/timeline lookups (which parse
        that number back out of the filename) keep working unmodified.

        Mixed per leg, not all-or-nothing: a leg whose mode is in
        tuning.RESIDENTIAL_2D_FALLBACK_MODES (currently just airplane —
        ferry now gets the chase camera too, via pedestrian.py's own
        "ferry" HUD mode) is handed to the flat 2D renderer for that leg
        alone, and the legs either side of
        it still get the chase camera. render_waypoints names its output
        from each leg's own `start_pos` rather than its position in the list
        it was given, so rendering a single leg through it produces exactly
        the same filename it would have had in a full-sequence run.
        """
        from services.vdoprocessing.pydeckrecorder.pedestrian import render_residential_leg_pydeck
        from services.vdoprocessing.videopipeline.helpers import attraction_output_filename

        # Maps a waypoint's stable job_config "id" to its RAW 0-based
        # position in job_config's own "waypoints" array -- the same index
        # helpers.attraction_output_filename names that waypoint's
        # attraction-video file with. Built once here (not from
        # render_step.py's own res_waypoints, which can have a synthetic
        # start/end point PREPENDED -- see render_step.py's own comment on
        # that -- shifting every real position by one) so a connected
        # stop-by's attraction-video lookup below always matches the file
        # the attraction pipeline actually produced.
        waypoint_id_to_idx: Dict[str, int] = {}
        attraction_dir = None
        job_config_path = self.config.get("res_route_path")
        if job_config_path and os.path.exists(job_config_path):
            try:
                with open(job_config_path, "r", encoding="utf-8") as f:
                    _raw_job_config = json.load(f)
                for _idx, _wp in enumerate(_raw_job_config.get("waypoints", [])):
                    if _wp.get("id"):
                        waypoint_id_to_idx[_wp["id"]] = _idx
                # Route and attraction outputs are SIBLING subfolders under
                # the same assets/video/ parent (see helpers.py's own
                # project_route_video_dir/project_attraction_video_dir) --
                # self.out_dir IS project_route_video_dir already, so its
                # sibling is exactly project_attraction_video_dir without
                # needing to re-derive the project root path.
                attraction_dir = self.out_dir.parent / "attraction"
            except (OSError, json.JSONDecodeError) as e:
                logger.warning(f"Could not read job_config for attraction-video lookup: {e}")

        def _attraction_video_for(waypoint_id: Optional[str], label: Optional[str]) -> Optional[str]:
            if not waypoint_id or waypoint_id not in waypoint_id_to_idx or attraction_dir is None:
                return None
            idx = waypoint_id_to_idx[waypoint_id]
            candidate = attraction_dir / attraction_output_filename(idx, label or f"waypoint_{idx}")
            return str(candidate) if candidate.exists() else None

        output_paths = []
        # Was only ever set once, well before this loop ("Rendering
        # residential video...") -- gps_commands.py's test_residential_video
        # (and the real pipeline the same way) then sat on that one static
        # line for the ENTIRE multi-minute render, across every leg, with no
        # further tracker calls anywhere in this function, looking frozen
        # even though work was actively happening. begin_substeps/show_item
        # give it a live per-leg "[i/N] rendering leg -> label" line instead
        # -- pedestrian.py's own tracker calls inside render_residential_leg_
        # pydeck further subdivide THIS leg's own share of that line.
        tracker.begin_substeps(len(res_sequence))
        for i, res_data in enumerate(res_sequence):
            # Each leg launches its own Chromium; don't start one with no RAM left.
            tuning.ensure_free_ram(f"residential leg {i + 1}", self.config.get("min_free_ram_gb"))
            lats, lons = res_data.get("lats"), res_data.get("lons")
            leg_latlon = list(zip(lats, lons)) if lats is not None and lons is not None else []
            if len(leg_latlon) < 2:
                logger.warning(f"Skipping residential leg {i}: no usable lat/lon track.")
                continue

            leg_labels = [l for l in res_data.get("labels", []) if l]
            dest_label = leg_labels[-1] if leg_labels else "目的地"
            tracker.show_item(i + 1, f"Rendering residential leg {i + 1}/{len(res_sequence)} -> {dest_label}")
            leg_mode = res_data.get("mode") or "walking"
            leg_mode = tuning.MODE_ALIASES.get(str(leg_mode).lower(), str(leg_mode).lower())

            if leg_mode in tuning.RESIDENTIAL_2D_FALLBACK_MODES:
                logger.info(
                    f"Residential leg {i} is '{leg_mode}' — rendering it with the "
                    "2D SpatialRenderer instead of the chase camera."
                )
                output_paths.extend(
                    self.spatial_renderer.render_waypoints([res_data], fps)
                )
                continue
            # The leg's own already-computed VIDEO length (narration-synced
            # when audio exists, else a paced distance fallback — see
            # render_step.py's res_sequence build) — real routes range from
            # a few meters to several kilometers per leg, so animating at
            # literal real-world walking/ferry pace would make clips
            # anywhere from seconds to literal HOURS long. Does not affect
            # the HUD's own displayed remaining-time estimate, which stays
            # real-world (see render_residential_leg_pydeck's docstring).
            target_duration = res_data.get("travel_duration") or res_data.get("segment_duration")

            landmarks = [
                {
                    "lat": m["lat"], "lon": m.get("lng", m.get("lon")), "label": m.get("label"),
                    # "connectToRoute" stop-bys (job_config.json's own
                    # per-waypoint toggle -- see mapfetcher.py's own
                    # "connect_to_route" field) get the full fullscreen
                    # photo-pause treatment as the walker passes them,
                    # mirroring the overview's own rule that a connected
                    # stop-by acts like a real waypoint rather than a
                    # silent pass-through pin (see render_residential_leg_
                    # pydeck's `landmarks` docstring).
                    "connect_to_route": bool(m.get("connect_to_route", False)),
                    "popup_image": m.get("popup_image"),
                    "freeze_seconds": m.get("freeze_seconds"),
                    "image_display": m.get("image_display", "cover"),
                    # This stop-by's own real narration length (see
                    # mapfetcher.py's "narration_audio_seconds") -- lets
                    # pedestrian.py hold its fullscreen photo-pause at least
                    # this long instead of cutting away at the short fixed
                    # freeze_seconds cap while the narration is still
                    # playing underneath.
                    "narration_audio_seconds": m.get("narration_audio_seconds"),
                    # Only set when this connected stop-by's waypoint
                    # already has a GENERATED attraction video on disk (the
                    # separate img2vdo.py/attraction_step.py pipeline stage
                    # -- residential rendering never generates one itself).
                    # When set, the fullscreen photo-pause cuts the leg
                    # clip instead of shrinking back to resume the walk in
                    # place -- see pedestrian.py's `landmarks` docstring.
                    "attraction_video": _attraction_video_for(m.get("waypoint_id"), m.get("label")),
                    # The photo ends fullscreen and the attraction video
                    # dissolves in from it (no hold, no blur-out here).
                    "dissolve_into_attraction": bool(self.config.get("dissolve_into_attraction", False)),
                    # Audio-first timing of the walk TOWARD this stop and how long
                    # it waits here for the voice (render_step.py's piece plan).
                    "walk_seconds": m.get("walk_seconds"),
                    "wait_seconds": m.get("wait_seconds"),
                }
                for m in res_data.get("mid_markers", [])
                if m.get("lat") is not None and m.get("lng", m.get("lon")) is not None
            ]

            # Every connectToRoute landmark in THIS leg, in the same order
            # `landmarks` (and therefore pedestrian.py's own cut sequence)
            # visits them -- each one cuts the leg into one more piece (see
            # `landmarks` docstring above). Each piece is the WALK TOWARD
            # its own next stop, so piece[k] (0-based) "targets" landmark[k]
            # -- its own narration plays during that walk, and its own
            # fullscreen pause (which follows immediately) holds until that
            # narration finishes -- except the LAST piece, which has no
            # landmark ahead of it and targets the leg's actual destination
            # waypoint instead. Written out as a small sidecar JSON below so
            # leg_pieces.py's narration split (done later, once audio_paths
            # are available -- this method has no access to them) knows
            # which waypoint's own narration belongs to which piece.
            connected_landmark_ids = [
                m.get("waypoint_id")
                for m in res_data.get("mid_markers", [])
                if m.get("connect_to_route")
                and m.get("lat") is not None
                and m.get("lng", m.get("lon")) is not None
            ]
            leg_destination_id = res_data.get("end_waypoint_id")

            def _write_piece_plan(piece_paths) -> None:
                plan = {
                    "pieces": [
                        {
                            "file": Path(p).name,
                            "target_waypoint_id": (
                                connected_landmark_ids[idx]
                                if idx < len(connected_landmark_ids)
                                else leg_destination_id
                            ),
                        }
                        for idx, p in enumerate(piece_paths)
                    ]
                }
                plan_path = self.out_dir / f"02_waypoint_{leg_file_num:02d}_pieces.json"
                try:
                    with open(plan_path, "w", encoding="utf-8") as f:
                        json.dump(plan, f, ensure_ascii=False)
                except OSError:
                    pass

            # render_step.py stashes the destination waypoint's own popup
            # data as the LAST entry of this leg's "popups" list (every
            # other position is None — a residential clip only ever ends
            # its route on the arrival stop, never the departure one). Its
            # photo opens this leg's clip full-bleed before shrinking down
            # to the normal card size (see render_residential_leg_pydeck's
            # `dest_popup_image` docstring).
            dest_popup = next(
                (p for p in (res_data.get("popups") or []) if p), None
            ) or {}
            # "popup_image_last" (not "popup_image") -- residential shows
            # the LAST of a multi-image waypoint's photos; the overview
            # animation reads "popup_image" (the first) for this same
            # waypoint and is unaffected by this choice.
            # The leg ends on this photo and the destination's attraction video
            # follows it (timeline_step.py, with a dissolve): that video opens on
            # the waypoint's FIRST image, so with attraction videos on, the
            # leg shows the first image too and the two meet on the same frame.
            # Without them, the last image, as before.
            dest_popup_image = (
                dest_popup.get("popup_image")
                if self.config.get("enable_attraction_videos", True)
                else dest_popup.get("popup_image_last")
            ) or dest_popup.get("popup_image_last") or dest_popup.get("popup_image")
            dest_freeze_seconds = dest_popup.get("freeze_seconds")
            dest_narration_seconds = dest_popup.get("audio_duration")
            dest_image_display = dest_popup.get("image_display") or "cover"
            if not dest_popup_image:
                # A trailing synthetic end_point leg's own destination has
                # no popup of its own (see render_step.py's
                # "trip_end_popup" comment) -- fall back to the last REAL
                # waypoint's own photo so the video's truly final clip still
                # arrives on a photo instead of nothing. No-op (same value
                # dest_popup already held) whenever the last real waypoint
                # IS this leg's own destination, since there's no trailing
                # synthetic leg in that case.
                end_popup = res_data.get("trip_end_popup") or {}
                dest_popup_image = end_popup.get("popup_image_last") or end_popup.get("popup_image")
                dest_freeze_seconds = end_popup.get("freeze_seconds")
                dest_narration_seconds = end_popup.get("audio_duration")
                dest_image_display = end_popup.get("image_display") or dest_image_display

            # Every leg's own departure waypoint's popup (see render_step.py's
            # "leg_start_popup" comment) -- shown at THIS leg's own opening,
            # independent of whether the previous leg's arrival preview
            # already showed the same waypoint's photo once.
            start_popup = res_data.get("leg_start_popup") or {}
            start_popup_image = start_popup.get("popup_image_last") or start_popup.get("popup_image")
            start_freeze_seconds = start_popup.get("freeze_seconds")
            start_narration_seconds = start_popup.get("audio_duration")

            safe_suffix = (
                "".join(c for c in str(dest_label) if c.isalnum() or c in (" ", "_", "-"))
                .strip()
                .replace(" ", "_")
                or f"leg{i + 1}"
            )
            leg_file_num = res_data.get("start_pos")
            leg_file_num = (leg_file_num + 1) if leg_file_num is not None else (i + 1)
            chunk_filename = f"02_waypoint_{leg_file_num:02d}_{safe_suffix}.mp4"

            output_path = str(self.out_dir / chunk_filename)

            # Checkpoint: a connected stop-by can split ONE leg into
            # several output files sharing this leg's "02_waypoint_{N:02d}_"
            # prefix (see the comment just below), so "already rendered" is
            # checked by that whole prefix, not just the base filename —
            # otherwise a previously-cut leg would look unfinished (base
            # file missing) even though every _contN piece is there, and
            # get re-rendered from scratch. Simple existence check, no
            # content hash — same resume-not-diff semantics as the overview
            # checkpoint above.
            leg_glob_prefix = f"02_waypoint_{leg_file_num:02d}_"
            existing_leg_files = sorted(
                p for p in self.out_dir.glob(f"{leg_glob_prefix}*.mp4")
                if _output_is_valid(p)
            ) if self.config.get("checkpoint_enabled", False) else []
            if existing_leg_files:
                logger.info(
                    "Residential leg %d already rendered (%d file(s)) — skipping.",
                    leg_file_num, len(existing_leg_files),
                )
                # Rewritten even on a checkpoint skip -- cheap (no ffmpeg),
                # and keeps it in sync with job_config's CURRENT
                # connectToRoute/landmark data even when the video itself
                # wasn't re-rendered this run.
                _write_piece_plan([str(p) for p in existing_leg_files])
                output_paths.extend(str(p) for p in existing_leg_files)
                continue

            # A connected stop-by's fullscreen photo pause (see pedestrian.
            # py's `landmarks` docstring) can cut this ONE leg into more
            # than one output file -- render_residential_leg_pydeck always
            # returns a LIST now, every entry sharing this same leg's own
            # "02_waypoint_{N:02d}_" filename prefix (just a "_cont{n}"
            # suffix added per cut), so downstream (timeline_step.py) still
            # resolves each one back to this leg by filename -- and, when
            # there's more than one piece, splits this leg's own narration/
            # subtitle across them (see leg_pieces.py), each landmark's own
            # piece opening on ITS OWN narration before continuing the
            # leg's departure narration, instead of the same departure
            # narration restarting on every piece.
            leg_paths = render_residential_leg_pydeck(
                leg_latlon, dest_label, output_path, mode=leg_mode,
                target_duration_seconds=target_duration,
                landmarks=landmarks, route_chain=leg_labels or None,
                # Straight-down bird's-eye chase cam (still follows/rotates
                # with the walker, just never tilts) rather than the
                # angled 55deg default — settings.res_follow_pitch lets a
                # project opt back into the tilted look.
                follow_pitch=self.config.get("res_follow_pitch", 0.0),
                dest_popup_image=dest_popup_image,
                dest_popup_freeze_seconds=dest_freeze_seconds,
                dest_popup_narration_seconds=dest_narration_seconds,
                start_popup_image=start_popup_image,
                start_popup_freeze_seconds=start_freeze_seconds,
                start_popup_narration_seconds=start_narration_seconds,
                start_cue_seconds=res_data.get("start_cue_seconds"),
                arrival_photo_hold_seconds=self.config.get("arrival_photo_hold_seconds"),
                arrival_wait_seconds=res_data.get("arrival_wait_seconds"),
                dest_image_display=dest_image_display,
            )
            _write_piece_plan(leg_paths)
            output_paths.extend(leg_paths)

        return output_paths

    def render(
        self,
        img_path: str,
        points: List,
        labels: List,
        popups: List,
        fps: int = 30,
        res_sequence: Optional[List] = None,
        summary: Optional[Dict] = None,
        wp_indices: Optional[List[int]] = None,
        point_modes: Optional[List[str]] = None,
        render_mode: str = "both",
        **kwargs,
    ) -> List[str]:
        """Main rendering orchestrator. Decides which rendering engine to use.

        render_mode ("both"/"overview"/"residential") gates which of the
        two output videos actually gets rendered — "residential" skips the
        overview animation entirely (render_overview is never even called,
        so none of its compute is paid for); "overview" relies on
        render_step.py having already left res_sequence empty, but is also
        checked explicitly here so a caller that passes render_mode
        without also gating res_sequence itself still gets isolated
        output."""
        if not os.path.exists(img_path):
            logger.error(f"Background path does not exist: {img_path}")
            raise FileNotFoundError(f"Background path does not exist: {img_path}")

        output_paths = []

        # [HACK] [Core] No StoryboardRenderer implementation exists anywhere in this codebase, so use_leg_storyboard can never actually run — fail loudly here instead of an opaque AttributeError deep in a dead branch.
        if self.config.get("use_leg_storyboard", False) and wp_indices:
            raise NotImplementedError(
                "use_leg_storyboard is enabled but no StoryboardRenderer is "
                "implemented — use the default spatial renderer instead."
            )

        if render_mode != "residential":
            tracker.show("Rendering overview video...")
            # [NOTE] [Core] Overview kept on the 2D spatial_renderer path
            # deliberately, independent of use_pydeck_pedestrian (which
            # still governs residential below) — the GeoJsonLayer overview
            # (_render_overview_pydeck/render_overview_video_pydeck in
            # pydeckrecorder.pedestrian) works and is tested, just not
            # preferred for this project yet. Flip use_pydeck_overview in
            # settings to opt back in without any code change.
            if self.config.get("use_pydeck_overview", False):
                logger.info("Rendering Overview using GeoJsonLayer PyDeck...")
                overview_path = self._render_overview_pydeck(
                    img_path, points, labels, popups,
                    extent=kwargs.get("overview_extent"), fps=fps,
                )
            else:
                overview_path = self.spatial_renderer.render_overview(
                    img_path, points, labels, popups, fps, summary=summary, point_modes=point_modes,
                    bounding_box=kwargs.get("overview_bounding_box"),
                    extent=kwargs.get("overview_extent"),
                )
            tracker.clear()
            if overview_path:
                # Skip the extra hold when the clip already ended itself on
                # a blur-out (see SpatialRenderer._render_ending_highlight) —
                # that blur is meant to be the video's actual last frame, so
                # freezing on top of it just makes playback linger instead
                # of ending right when the blur finishes.
                if not self.spatial_renderer.last_ending_hard_ended:
                    self._freeze_video_end(
                        overview_path,
                        hold_seconds=self.config.get(
                            "summary_hold", DEFAULT_SUMMARY_HOLD_SECONDS
                        ),
                    )
                output_paths.append(overview_path)

        # [NOTE] [Core] Render each waypoint-to-waypoint leg. The GeoJsonLayer
        # PyDeck chase camera (top-down overview -> tilted follow, per leg)
        # is now the DEFAULT residential engine — set use_pydeck_pedestrian
        # to false in a project's settings to opt back into either the
        # older vehicle-scenegraph use_3d_res pipeline or, with both flags
        # false, the flat 2D SpatialRenderer.
        if res_sequence and render_mode != "overview":
            if self.config.get("use_pydeck_pedestrian", True):
                logger.info(
                    "Rendering Residential Sequence using GeoJsonLayer PyDeck (chase camera)..."
                )
                output_paths.extend(self._render_residential_pydeck(res_sequence, fps))
            elif self.config.get("use_3d_res", False):
                logger.info(
                    "Attempting Residential Sequence using 3D PyDeck (Split by Leg)..."
                )
                res_route_path = self.config.get("res_route_path")
                res_out_path = str(self.out_dir / "02_residential_map.mp4")
                audio_durs = [
                    seg.get("segment_duration", 0.0) for seg in res_sequence
                ]
                final_res_paths = record_headless_video(
                    res_route_path,
                    res_out_path,
                    audio_durations=audio_durs,
                    speed_kmh=60,
                )
                if not final_res_paths:
                    raise RuntimeError("3D rendering generated an empty output sequence.")
                output_paths.extend(final_res_paths)
            else:
                logger.info(
                    "Rendering Residential Sequence using 2D SpatialRenderer..."
                )
                output_paths.extend(self.spatial_renderer.render_waypoints(res_sequence, fps))

        return output_paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--output", default="data\\outputs\\video")
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--thickness", type=int, default=None)
    parser.add_argument("--radius", type=int, default=None)
    parser.add_argument("--res-map", default=None)
    parser.add_argument("--res-route", default=None)
    parser.add_argument("--res-duration", type=float, default=12.0)
    parser.add_argument("--pause", type=float, default=2.0)
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--summary-hold", type=float, default=4.0)
    parser.add_argument("--summary-fade", type=float, default=0.5)
    parser.add_argument(
        "--use-storyboard", action="store_true", help="Slice the overview video"
    )

    args = parser.parse_args()

    config = {
        "output_dir": args.output,
        "pause": args.pause,
        "summary_hold": args.summary_hold,
        "summary_fade": args.summary_fade,
        "res_duration": args.res_duration,
        "use_leg_storyboard": args.use_storyboard,
    }

    animator = RouteAnimator(config)
    points, labels, popups, settings = animator.load_route_data(args.route)

    animator.config["fps"] = args.fps or settings.get("fps", 30)
    animator.config["duration"] = args.duration or settings.get("duration_seconds", 8)
    animator.graphics.line_thickness = args.thickness or settings.get(
        "line_thickness", DEFAULT_LINE_THICKNESS
    )
    animator.graphics.marker_radius = args.radius or settings.get(
        "marker_radius", DEFAULT_MARKER_RADIUS
    )

    res_sequence = None
    if args.res_route and args.res_map:
        res_points, res_labels, res_popups, _ = animator.load_route_data(args.res_route)

        # [HACK] [IO] Walks up from the output dir looking for job_config.json
        # since this CLI has no direct reference to the job — swallows any
        # read failure and just falls back to the raw route labels.
        try:
            out_path = Path(args.output)
            job_paths = [
                out_path / "job_config.json",
                out_path.parent / "job_config.json",
            ]

            for job_config_path in job_paths:
                if job_config_path.exists():
                    with open(job_config_path, "r", encoding="utf-8") as f:
                        job_data = json.load(f)
                        start_lbl = job_data.get("start_point", {}).get("label")
                        end_lbl = job_data.get("end_point", {}).get("label")

                        if start_lbl and len(res_labels) > 0:
                            res_labels[0] = start_lbl
                        if end_lbl and len(res_labels) > 1:
                            res_labels[-1] = end_lbl
                    break
        except Exception as e:
            logger.warning(
                f"Could not read labels from job_config.json for residential map: {e}"
            )

        res_sequence = [
            {
                "img_path": args.res_map,
                "points": res_points,
                "labels": res_labels,
                "popups": res_popups,
            }
        ]

    summary = (
        json.load(open(args.summary_json, "r", encoding="utf-8"))
        if args.summary_json
        else None
    )

    # [NOTE] [Core] Forces the route's first/last points into wp_indices even without a popup so storyboard slicing always has a defined start/end leg.
    wp_indices = [i for i, pop in enumerate(popups) if pop is not None]

    if 0 not in wp_indices:
        wp_indices.insert(0, 0)
    if len(points) - 1 not in wp_indices:
        wp_indices.append(len(points) - 1)

    output_files = animator.render(
        img_path=args.map,
        points=points,
        labels=labels,
        popups=popups,
        res_sequence=res_sequence,
        summary=summary,
        wp_indices=wp_indices,
    )

    logger.info(f"Rendered {len(output_files)} file(s):")
    for f in output_files:
        logger.info(f"   {f}")


if __name__ == "__main__":
    main()

Route2VDO = RouteAnimator