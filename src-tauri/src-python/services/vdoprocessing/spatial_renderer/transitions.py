"""Cut/fade and blur-out transition primitives, plus the end-of-video recap,
summary card, and higher-zoom "callback to where the journey began" highlight."""

import math
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter
from services import tuning
from services.mapbox_token import resolve_mapbox_token
from services.mapfetcher.graphicengine.pinimage import marker_for

from .base import logger

# The ending highlight's final hold stretches for leftover narration (see
# _render_ending_highlight's remaining_audio_seconds), but never past this.
_MAX_ENDING_HIGHLIGHT_HOLD_SECONDS = 15.0


class _TransitionMixin:
    # Divisor/floor used to size _blur_out's max Gaussian kernel radius
    # relative to the frame's short edge (see the comment at its call site).
    _BLUR_KSIZE_DIVISOR = 20
    _BLUR_MIN_KSIZE = 3

    # Default hold time (seconds) used when a popup's own "freeze_seconds"
    # is absent from its data.
    _DEFAULT_FREEZE_SECONDS = 3.0

    # Multiplier on marker_radius used to decide whether a nearby waypoint
    # pin would land close enough to the featured pin to be treated as
    # "the same point" and skipped in _draw_nearby_waypoints.
    _SAME_POINT_RADIUS_MULTIPLIER = 2

    # Multiplier on max(w, h) used to bound the off-screen margin route
    # points get clamped to in _draw_route_line_on_extent.
    _ROUTE_LINE_MARGIN_MULTIPLIER = 5

    @staticmethod
    def _ken_burns_hold(
        video: VideoExporter,
        frame: np.ndarray,
        fps: int,
        duration_sec: float,
        zoom_cx: float,
        zoom_cy: float,
        zoom_from: float = 1.0,
        zoom_to: float = 1.18,
    ) -> np.ndarray:
        """Slow, continuous zoom-in on `frame` itself while it's held on
        screen (the classic Ken Burns photo effect), toward (zoom_cx,
        zoom_cy), instead of holding one static frame. No second image
        involved and no cut/fade to build or align — `frame` is already
        the genuinely higher-zoom, freshly fetched tile, so this is just
        motion added to what's already on screen. Kept to a modest zoom
        range (well under 2x) so the source stays crisp — it's magnifying
        pixels that are already there, so a large zoom would soften
        visibly, but this range doesn't. Returns the final (most-zoomed)
        frame written, so a later hold can continue the zoom from there."""
        h, w = frame.shape[:2]
        total_frames = max(1, int(duration_sec * fps))
        last = frame
        for frame_idx in range(total_frames):
            progress = frame_idx / max(1, total_frames - 1)
            zoom = zoom_from + (zoom_to - zoom_from) * progress
            crop_w, crop_h = w / zoom, h / zoom
            cx = min(max(zoom_cx, crop_w / 2), w - crop_w / 2)
            cy = min(max(zoom_cy, crop_h / 2), h - crop_h / 2)
            x0, y0 = int(cx - crop_w / 2), int(cy - crop_h / 2)
            x1, y1 = int(x0 + crop_w), int(y0 + crop_h)
            x0, y0 = max(0, x0), max(0, y0)
            x1, y1 = min(w, x1), min(h, y1)
            last = cv2.resize(
                frame[y0:y1, x0:x1], (w, h), interpolation=cv2.INTER_CUBIC
            )
            video.write(last)
        return last

    def _blur_out(
        self, video: VideoExporter, frame: np.ndarray, fps: int, duration_sec: float = 0.5
    ) -> np.ndarray:
        """Writes a progressive out-of-focus blur of `frame` (increasing
        Gaussian blur radius each frame) as a soft closing beat, and
        returns the final, most-blurred frame. Used as the video's actual
        last frames instead of a hard cut or fade-to-black — a bare cut
        would jump straight into whatever plays next, and this reads
        smoothly even when the next clip opens on this exact picture."""
        total_frames = max(1, int(duration_sec * fps))
        max_ksize = max(
            self._BLUR_MIN_KSIZE, (min(frame.shape[:2]) // self._BLUR_KSIZE_DIVISOR) | 1
        )  # odd, ~5% of the short edge
        blurred = frame
        for frame_idx in range(total_frames):
            ksize = max(1, round((frame_idx + 1) / total_frames * max_ksize)) | 1
            blurred = cv2.GaussianBlur(frame, (ksize, ksize), 0)
            video.write(blurred)
        return blurred

    def _render_recap_and_summary(
        self,
        video: VideoExporter,
        stop_popup: Optional[Dict],
        summary_card: Optional[np.ndarray],
        active_popups: List[Dict],
        w: int,
        h: int,
        fps: int,
        route_obstacle_arr: np.ndarray,
        reserved_boxes: List[Tuple[float, float, float, float]],
        pre_popup_frame: Optional[np.ndarray],
    ) -> float:
        """Builds the end-of-video recap and fades the summary stat card in
        on top of it, returning how long (seconds) the caller should hold
        on the result before moving on. Updates self.last_frame; does not
        write that final hold itself, since the highlight
        (_render_ending_highlight) may still need to run first.

        The recap shows EVERY waypoint's card at once, fading in together
        from the clean map in a single crossfade rather than trickling in a
        few at a time. The whole set is laid out up front into the frame's
        free space (see _layout_recap_cards) — disjoint slots, so no two
        cards can overlap, matched to pins by minimum total leader length,
        which leaves the lines both short and uncrossed — and every pin is
        already visible on `outro_frame` regardless. All of this is written
        directly here (not left to the caller's own trailing hold loop), so
        the returned outro_hold_sec covers only the summary card's own hold
        on top of the fully-revealed recap."""
        outro_hold_sec = 0.0
        outro_frame = None
        final_frame = None
        hold_frames = 0

        if stop_popup:
            # Clean plate (see pre_popup_frame's own comment above) rather
            # than self.last_frame, which can still have a not-yet-finished
            # popup fade-out baked into it — and it already has every
            # numbered pin drawn on it, so the recap doesn't need to
            # redraw them. The fullscreen photo comes later, in
            # _render_ending_highlight after the zoom — never here.
            outro_frame = (
                pre_popup_frame.copy() if pre_popup_frame is not None
                else self.last_frame.copy()
            )
            all_recap_popups = [ap for ap in active_popups if ap["data"].get("popup_image")]
            # A loop route's "E" is the exact same real-world place as "S"
            # (see SpatialRendererBase._is_loop_route) — usually labeled
            # "... (Return)" in job_config.json, its own popup card would
            # otherwise show the same photo/place right next to the start
            # card it's a duplicate of. Drop it here (by identity, not by
            # label text) so the recap shows that place once, via its
            # start-popup card, rather than twice.
            if self._is_loop_route and stop_popup is not None:
                all_recap_popups = [ap for ap in all_recap_popups if ap is not stop_popup]
            total_freeze = float(
                stop_popup["data"].get("freeze_seconds", self._DEFAULT_FREEZE_SECONDS)
            )
            hold_frames = max(0, int(total_freeze * fps))

            if all_recap_popups:
                laid_out = self._layout_recap_cards(
                    all_recap_popups, w, h,
                    reserved_boxes=reserved_boxes,
                    route_obstacles=route_obstacle_arr,
                )
                final_frame = self._render_recap_frame(
                    outro_frame, active_popups, group_popups=laid_out
                )
            else:
                final_frame = outro_frame

        # The summary card is composited onto the SAME target frame the
        # recap cards fade into, and both cross-fade in together below —
        # it used to fade in on its own, after the recap cards had already
        # settled and held, which read as two separate reveals.
        if summary_card is not None:
            base = final_frame if final_frame is not None else self.last_frame
            final_frame = self.graphics.composite_card_on_frame(base, summary_card, alpha=1.0)
            outro_hold_sec = max(
                outro_hold_sec, float(self.config.get("summary_hold", 4.0))
            )

        if final_frame is not None:
            source = outro_frame if outro_frame is not None else self.last_frame
            fade_sec = max(
                tuning.RECAP_GROUP_FADE_SECONDS, float(self.config.get("summary_fade", 0.5))
            )
            fade_frames = max(1, int(fade_sec * fps))
            for i in range(fade_frames):
                alpha = (i + 1) / fade_frames
                video.write(cv2.addWeighted(final_frame, alpha, source, 1 - alpha, 0))
            for _ in range(max(0, hold_frames - fade_frames)):
                video.write(final_frame)
            self.last_frame = final_frame

        return outro_hold_sec

    # How long to hold the higher-zoom map (with its marker + leader-lined
    # popup) before handing off to the fullscreen photo transition — the
    # "switch to higher map, then wait a bit" beat.
    # Timing/zoom values below live in services/tuning.py — the shared home
    # for hand-tunable constants across spatial_renderer + graphicengine.
    _ENDING_HIGHLIGHT_WAIT_SECONDS = tuning.ENDING_HIGHLIGHT_WAIT_SECONDS

    # How long to push in on the CURRENT wide map (before cutting to the
    # freshly fetched close-up tile) so the highlight beat reads as
    # "zooming FROM the big map INTO the start point" rather than a
    # close-up simply appearing. Longer duration = smaller per-frame zoom
    # step at the same fps = a smoother push, less of a "skip" feel right
    # up to the cut.
    _BIG_MAP_ZOOM_LEAD_SECONDS = tuning.BIG_MAP_ZOOM_LEAD_SECONDS
    # How far that lead-in push zooms in, before the cut — pushed further
    # in than before (1.9x) so the map is already close to the residential
    # sequence's own zoom level by the time it cuts, rather than stopping
    # at a middling zoom and leaving a second, more noticeable jump for the
    # residential clip that follows this video.
    _BIG_MAP_ZOOM_TARGET = tuning.BIG_MAP_ZOOM_TARGET

    def _draw_route_line_on_extent(
        self,
        frame: np.ndarray,
        w: int,
        h: int,
        extent: Tuple[float, float, float, float],
    ) -> None:
        """Redraws the route line on a freshly fetched close-up tile — the
        ending highlight's own extent is a genuinely different (much more
        zoomed-in) map than the main overview render, so the pixel-space
        path drawn there doesn't carry over; this reprojects the lat/lon
        route (stashed by render_overview as self._route_latlon_path) onto
        THIS frame's extent instead. Drawn before pins/markers so it sits
        underneath them, matching the main overview's own draw order. A
        no-op when there's no stashed route (e.g. render_overview wasn't
        given an extent to reproject from in the first place)."""
        route_latlon = getattr(self, "_route_latlon_path", None)
        if not route_latlon:
            return
        pts = [
            RouteGeometryProcessor.project_latlon_to_pixel(lat, lon, extent, w, h)
            for lat, lon in route_latlon
        ]
        # Generous but bounded margin — keeps genuinely nearby off-screen
        # stretches connecting properly across the frame edge without
        # letting a wildly out-of-view point blow up into huge coordinates.
        margin = max(w, h) * self._ROUTE_LINE_MARGIN_MULTIPLIER
        pts = [
            (int(min(max(px, -margin), w + margin)), int(min(max(py, -margin), h + margin)))
            for px, py in pts
        ]
        arr = np.array(pts, dtype=np.int32)
        if self.graphics.line_border_thickness:
            cv2.polylines(
                frame, [arr], False, self.graphics.line_border_color,
                self.graphics.line_thickness + self.graphics.line_border_thickness * 2,
                cv2.LINE_AA,
            )
        cv2.polylines(
            frame, [arr], False, self.graphics.line_color,
            self.graphics.line_thickness, cv2.LINE_AA,
        )

    def _draw_nearby_waypoints(
        self,
        frame: np.ndarray,
        w: int,
        h: int,
        extent: Tuple[float, float, float, float],
        exclude_px: int,
        exclude_py: int,
    ) -> None:
        """Draws a pin for every OTHER job_config waypoint that happens to
        fall inside this freshly fetched close-up tile — the featured
        waypoint (at exclude_px/exclude_py) gets its own dedicated marker
        drawn separately by the caller, so it's skipped here. Uses the
        same S/E/stop-by/number precedence as everywhere else (via
        _pin_label_and_color), computed from each waypoint's real
        position in job_config's own waypoints list."""
        job_waypoints = (self._get_job_config() or {}).get("waypoints", [])
        # job_config's own "waypoints" array holds only the INTERMEDIATE
        # stops — the true start/end live in separate "start_point"/
        # "end_point" keys (see _render_ending_highlight's own zoom_point
        # lookup) — so index 0 / len-1 here are just the first/last
        # intermediate stop, NOT the route's real S/E. Without the +1/+2
        # offset, _pin_label_and_color's own index==0 / index==total-1
        # checks (written assuming the FULL route's points array, where
        # those positions genuinely ARE S/E) mislabeled those two
        # intermediate waypoints as "S"/green and "E"/red.
        total_wp = len(job_waypoints)
        total_points = total_wp + 2
        order = 0
        for pos, jw in enumerate(job_waypoints):
            is_stopby = bool(jw.get("isStopBy", False) or jw.get("skipAssetGeneration"))
            if not is_stopby:
                order += 1
            # A loop route's job_config waypoints list ends with a
            # synthetic "(Return)" entry at the SAME coordinates as the
            # route's own start/end — the real S/E pin already covers
            # that point (see _is_loop_route's half-green/half-red pin
            # elsewhere). The exclude_px/exclude_py check below is meant
            # to filter this out too (same coords as the featured point),
            # but at this highlight's high zoom, a tiny lat/lng rounding
            # difference between this entry and the true end_point can
            # put it just outside that pixel radius — showing up as an
            # extra, oddly-numbered pin sitting right next to S/E (e.g.
            # "12" for a 10-stop route). Skipped outright here instead of
            # relying on the distance check to catch it.
            if self._is_loop_route and pos == total_wp - 1:
                continue
            lat, lng = jw.get("lat"), jw.get("lng", jw.get("lon"))
            if lat is None or lng is None:
                continue
            px, py = RouteGeometryProcessor.project_latlon_to_pixel(lat, lng, extent, w, h)
            px, py = int(px), int(py)
            if not (0 <= px <= w and 0 <= py <= h):
                continue
            if (
                math.hypot(px - exclude_px, py - exclude_py)
                < self.graphics.marker_radius * self._SAME_POINT_RADIUS_MULTIPLIER
            ):
                continue  # the featured waypoint itself
            # "arrived": True — this only ever runs at the very end of
            # the video, once the whole route (every waypoint) has
            # genuinely been visited, so every pin here should show its
            # own arrived_marker_color, same as it does for the rest of
            # the video, rather than falling back to the DEFAULT
            # (not-yet-visited) marker_color — visibly wrong whenever a
            # project has customized the two to different colors.
            wp = {"index": pos + 1, "order": order, "data": {"is_stopby": is_stopby, "arrived": True}}
            label, color, split_color = self._pin_label_and_color(wp, total_points)
            self.graphics.draw_marker(
                frame, px, py, number=label, color=color, split_color=split_color,
                is_circle=bool(is_stopby),
                image=marker_for(jw, {"routeMarker": (self.config or {}).get("route_marker")}, (self.config or {}).get("marker_base_dir")),
            )

    def _gl_ending_zoom_enabled(self, bounding_box) -> bool:
        settings = (self._get_job_config() or {}).get("settings", {}) or {}
        return bounding_box is not None and (
            bool(settings.get("enable_gl_ending_zoom", True))  # on by default; false turns the pydeck zoom off
            or str(settings.get("overview_background", "")).lower() == "pydeck"
        )

    def _render_ending_highlight(
        self,
        video: VideoExporter,
        w: int,
        h: int,
        fps: int,
        stop_popup: Dict,
        start_popup: Optional[Dict] = None,
        clean_map_frame: Optional[np.ndarray] = None,
        bounding_box: Optional[Dict[str, float]] = None,
        remaining_audio_seconds: Optional[float] = None,
    ) -> bool:
        """End-of-video highlight: a hard cut (no transition) from the
        recap straight to a freshly fetched, genuinely higher-zoom map
        centered on the trip's START point — with its own marker and a
        leader-lined popup, featuring the start waypoint's own photo —
        then, while it's held, a slow continuous Ken Burns zoom-in on that
        same image (rather than a static freeze), before handing off to a
        fullscreen photo transition (if that waypoint's
        image_display is "fullscreen") or just hold on the pip card. A
        "callback to where the journey began" reveal to close the video,
        rather than repeating the end waypoint's own photo (already shown
        in the recap). Falls back to the end waypoint/point if there's no
        start one available.

        The highlight beat itself opens with a lead-in push toward the same
        point on `clean_map_frame` — a plain map+route+pins plate with no
        popup cards or the summary stat card baked in (pass the recap's own
        pre-popup-card frame here; falls back to self.last_frame, cards and
        all, if not given) — before the hard cut to the freshly fetched
        close-up tile. Zooming on the clean plate rather than self.last_frame
        (which by this point has every waypoint's leader-lined photo card
        AND the summary card composited on top) keeps that lead-in a plain
        map push instead of dragging a screenful of cards along with it.

        When `bounding_box` is given AND settings.overview_background is
        "pydeck", the lead-in push and the cut-to-a-second-static-tile
        above are BOTH replaced by one continuous sequence of genuinely
        re-rendered deck.gl frames (mapfetcher.pydeck_overview.
        capture_pydeck_zoom_sequence) — the map itself gets visibly
        sharper terrain/street/building detail as it zooms in, rather
        than a digital crop of one already-fetched image. Falls back to
        the static-tile path automatically on any capture failure.

        Returns True if the fullscreen photo transition played and the
        caller should treat this as the video's hard ending (write nothing
        further) — the fullscreen photo, once reached, is meant to be the
        last thing the video shows, not fade back down to the map for a
        trailing pause. Returns False otherwise (pip hold, or this highlight
        didn't run at all — no point to zoom to, or the image fetch
        failed — never worth losing an otherwise-finished render over), in
        which case the caller's normal trailing pause still applies.

        `remaining_audio_seconds`, when given, is how much narration is
        still left to play once this highlight starts — its own final hold
        stretches to cover that (never shrinks below the tuning default),
        so the highlight stays up until the closing line (distance/stats)
        finishes, rather than the caller's own fixed floor cutting it off
        early with narration still playing over a frozen last frame."""
        job_config = self._get_job_config() or {}
        is_start = bool(job_config.get("start_point"))
        zoom_point = job_config.get("start_point") or job_config.get("end_point") or {}
        lat, lng = zoom_point.get("lat"), zoom_point.get("lng")
        if lat is None or lng is None:
            return False

        # The adjacent stop in the direction the journey actually
        # continues from here — biases the highlight's framing (see
        # choose_route_focus_view's `next_lat`/`next_lon`) so the shot
        # reads as "here's the stop, and here's the way from it" instead
        # of centring dead-on with no sense of where the route leads.
        # Zooming on the START: the next leg is the one heading AWAY from
        # it, i.e. the first waypoint. Zooming on the END (the
        # start_point-less fallback above): there's no further leg, so
        # bias toward the leg that arrives INTO it instead — the last
        # waypoint — which is the only "direction" left to show.
        job_waypoints = job_config.get("waypoints") or []
        if is_start:
            adjacent = job_waypoints[0] if job_waypoints else job_config.get("end_point")
        else:
            adjacent = job_waypoints[-1] if job_waypoints else job_config.get("start_point")
        next_lat = next_lon = None
        if isinstance(adjacent, dict):
            next_lat = adjacent.get("lat")
            next_lon = adjacent.get("lng", adjacent.get("lon"))

        # Every other waypoint (numbered stops AND stop-bys — a stop-by is
        # frequently the thing that ends up cropped, since it usually sits
        # just off the route line rather than on it) worth keeping in shot
        # alongside the route line itself — see choose_route_focus_view's
        # own must_fit_latlon docstring for how this is used (a reward,
        # never a hard requirement, so a genuinely unreachable point at
        # the chosen zoom is simply left out rather than breaking the
        # framing search).
        must_fit_latlon = [
            (jw["lat"], jw.get("lng", jw.get("lon")))
            for jw in job_waypoints
            if jw.get("lat") is not None and jw.get("lng", jw.get("lon")) is not None
        ]

        featured_popup = start_popup or stop_popup
        settings = (job_config.get("settings", {}) or {})
        # "enable_gl_ending_zoom" — the actual job_config.json setting
        # this feature is toggled by (also honors overview_background:
        # "pydeck" as an alternate opt-in, since a project already using
        # pydeck for its overview background naturally wants this too).
        use_dynamic_pydeck = self._gl_ending_zoom_enabled(bounding_box)
        # Diagnostic: pins down WHY this ever silently falls back to the
        # static-tile Ken Burns path (the try/except below only logs on an
        # outright exception — a False use_dynamic_pydeck, or a dynamic
        # capture that returns an empty/falsy result without raising,
        # leaves no trace otherwise).
        logger.info(
            "Ending highlight: use_dynamic_pydeck=%s (bounding_box_present=%s, "
            "enable_gl_ending_zoom=%s, overview_background=%r)",
            use_dynamic_pydeck, bounding_box is not None,
            settings.get("enable_gl_ending_zoom", True),
            settings.get("overview_background"),
        )
        # Always ends on the fullscreen photo; image_display is ignored.
        is_fullscreen = True
        # The pip picture is held only briefly (tuning), not the waypoint's
        # own freeze_seconds — unless there's still narration left once the
        # lead-in + wait have played, in which case the hold stretches to
        # cover it (capped, so a bad audio-length reading can't run away).
        highlight_hold_sec = float(tuning.ENDING_HIGHLIGHT_PIP_HOLD_SECONDS)
        if remaining_audio_seconds is not None:
            needed = remaining_audio_seconds - self._BIG_MAP_ZOOM_LEAD_SECONDS - self._ENDING_HIGHLIGHT_WAIT_SECONDS
            highlight_hold_sec = max(highlight_hold_sec, min(needed, _MAX_ENDING_HIGHLIGHT_HOLD_SECONDS))

        highlight_bg = None
        highlight_extent = None
        px = py = 0
        # Only set when the dynamic pydeck path actually ran — lets the
        # tail code below skip every _ken_burns_hold call entirely
        # instead of digitally zooming a frame that's already a genuine
        # real re-render.
        dynamic_zoomed_end = None
        dynamic_final_hold = None

        if use_dynamic_pydeck:
            # The camera actually MOVES only through the lead-in + wait
            # phases — capturing real re-rendered frames just for those
            # (zoom_n), reaching the target zoom by the end of the wait
            # phase. The further pip-hold phase (hold_n) then reuses that
            # SAME final real frame rather than continuing to re-render
            # more of the same already-reached view — a genuine hold
            # (matching what "hold" should mean) rather than an
            # imperceptibly slow continued zoom, and faster to both watch
            # (the same total zoom_boost now happens over fewer frames,
            # so it visibly moves quicker) and render (no extra browser
            # round-trips for frames that would've looked identical
            # anyway).
            try:
                from services.mapfetcher.pydeck_overview import capture_pydeck_zoom_sequence

                lead_in_n = max(1, int(self._BIG_MAP_ZOOM_LEAD_SECONDS * fps))
                wait_n = max(1, int(self._ENDING_HIGHLIGHT_WAIT_SECONDS * fps))
                # The pip card holds until the narration is done; the fullscreen
                # transition only starts after that.
                hold_n = max(1, int(highlight_hold_sec * fps))
                zoom_n = lead_in_n + wait_n

                # settings.mapbox_style_id lets a project swap in a custom
                # Mapbox Studio style (e.g. one with larger place-name
                # text) — same setting TileDownloader._build_provider
                # already honors for the raster/contextily overview path,
                # threaded through here too so a project that sets it gets
                # bigger labels on this GL path as well, not just the
                # static one. Falls back to pydeck's own default style.
                style_id = settings.get("mapbox_style_id")
                map_style = (
                    f"mapbox://styles/{style_id}" if style_id
                    else "mapbox://styles/mapbox/streets-v12"
                )
                dynamic_frames = capture_pydeck_zoom_sequence(
                    bounding_box, (w, h), lat, lng, zoom_n,
                    zoom_boost=tuning.ENDING_HIGHLIGHT_PYDECK_ZOOM_BOOST,
                    mapbox_key=resolve_mapbox_token(settings),
                    map_style=map_style,
                    # The route this video actually drew (stashed by
                    # render_overview — the same geometry
                    # _draw_route_line_on_extent redraws on the close-up),
                    # so the push settles on a view that keeps the line
                    # through this point in shot rather than zooming it
                    # out of frame.
                    route_latlon=getattr(self, "_route_latlon_path", None),
                    next_lat=next_lat, next_lon=next_lon,
                    must_fit_latlon=must_fit_latlon,
                )
                logger.info(
                    "Ending highlight: dynamic pydeck capture returned %d frame(s) "
                    "(requested zoom_n=%d).",
                    len(dynamic_frames) if dynamic_frames else 0, zoom_n,
                )
            except Exception:
                logger.warning(
                    "Dynamic pydeck ending-highlight zoom failed; falling back to "
                    "the static-tile Ken Burns version.", exc_info=True,
                )
                dynamic_frames = None

            if dynamic_frames:
                # The target point is panned to stay at the SAME pixel
                # across every frame (see capture_pydeck_zoom_sequence's
                # own docstring) — computed once from the last frame's
                # extent rather than per-frame, since by construction
                # every frame's extent projects it to the same spot.
                highlight_bg, highlight_extent = dynamic_frames[-1]
                px, py = RouteGeometryProcessor.project_latlon_to_pixel(
                    lat, lng, highlight_extent, w, h
                )
                px, py = int(px), int(py)

                highlight_popup = featured_popup.copy()
                highlight_popup["data"] = featured_popup["data"].copy()
                highlight_popup["x"], highlight_popup["y"] = px, py
                highlight_popup.pop("pin_x", None)
                highlight_popup.pop("pin_y", None)
                # `featured_popup` is the SAME dict active_popups has held
                # (and mutated) for the whole render — most recently by
                # the recap that just ran (see _layout_recap_cards), which
                # stamps "card_scale" (often well under 1.0, packing many
                # stops into one frame — down to 0.38 for a route with
                # enough stops), "beside_box" (a position in the WIDE
                # overview frame, meaningless on this close-up tile's own
                # extent), "leader_via" and "recap_line_color" directly
                # onto it. Left in place, popup_card_geometry reads that
                # leftover card_scale (render_popup_box's own docstring:
                # "card_scale = float(popup_info.get('card_scale', 1.0))")
                # and draws this highlight's card at whatever fraction the
                # recap happened to need — a viewer sees the SAME photo
                # rendered full-size everywhere else in the video and
                # shrunk to a fraction of that size here, for no reason
                # tied to this shot at all. Stripped so this card sizes
                # itself fresh, same as every other popup draw does.
                for _stale_key in ("card_scale", "beside_box", "leader_via", "recap_line_color"):
                    highlight_popup.pop(_stale_key, None)
                highlight_popup["hud_corner"] = None
                highlight_popup["draw_leader_line"] = True
                self._layout_recap_popups([{"popup": highlight_popup, "frames_left": 1}], w, h)
                # The photo sits on top of its pin (the free layout could
                # hang it below the start pin).
                self._place_cards_above_pins([highlight_popup], w, h, *self.graphics.beside_card_footprint())

                for frame_idx, (frame_bgr, extent) in enumerate(dynamic_frames):
                    frame_out = frame_bgr.copy()
                    # Re-projected fresh against THIS frame's own extent,
                    # same as _draw_nearby_waypoints just below — NOT
                    # pixel-fixed "by construction" as this used to assume:
                    # that guarantee only holds for the fixed-zoom-boost
                    # path in capture_pydeck_zoom_sequence: when
                    # route_latlon is passed (as it is here), the push
                    # instead straight-line-interpolates center+zoom
                    # toward choose_route_focus_view's chosen end view,
                    # which generally does NOT keep this point pinned to
                    # one screen pixel along the way. Using the LAST
                    # frame's projection for every earlier frame — the old
                    # behavior — left the marker sitting wherever that
                    # final pixel happened to be throughout the whole
                    # lead-in, including over open water on a route whose
                    # camera path crosses it, before "snapping" to the
                    # correct spot only once the push actually finished.
                    frame_px, frame_py = RouteGeometryProcessor.project_latlon_to_pixel(
                        lat, lng, extent, w, h
                    )
                    frame_px, frame_py = int(frame_px), int(frame_py)
                    # _draw_nearby_waypoints deliberately EXCLUDES the
                    # featured point itself — it's meant to be drawn
                    # separately below — so without drawing its own
                    # marker unconditionally here too, the start/end pin
                    # was simply missing from every lead-in frame.
                    self._draw_route_line_on_extent(frame_out, w, h, extent)
                    self._draw_nearby_waypoints(frame_out, w, h, extent, frame_px, frame_py)
                    if frame_idx < lead_in_n:
                        self.graphics.draw_marker(
                            frame_out, frame_px, frame_py,
                            number="S" if is_start else "E",
                            color=self._START_PIN_COLOR if is_start else self._END_PIN_COLOR,
                            image=highlight_popup["data"].get("pin_image"),
                        )
                    if frame_idx >= lead_in_n:
                        # The "hard cut to arrived" moment — before this
                        # frame the featured point is just a plain pin on
                        # the map, same as every other waypoint (matches
                        # the static-tile fallback's own lead-in, which
                        # shows no card either); from here on its
                        # leader-lined card joins it too. The card's own
                        # box was already laid out once (above) against
                        # the final settled position, so only the pin end
                        # of its leader line needs to track this frame's
                        # own (by now very close to final) position.
                        highlight_popup["x"], highlight_popup["y"] = frame_px, frame_py
                        frame_out = self.graphics.render_popup_box(
                            frame_out, highlight_popup, line_only=True
                        )
                        self.graphics.draw_marker(
                            frame_out, frame_px, frame_py,
                            number="S" if is_start else "E",
                            color=self._START_PIN_COLOR if is_start else self._END_PIN_COLOR,
                            image=highlight_popup["data"].get("pin_image"),
                        )
                        frame_out = self.graphics.render_popup_box(
                            frame_out, highlight_popup, skip_line=True
                        )
                    video.write(frame_out)
                    if frame_idx == lead_in_n + wait_n - 1:
                        dynamic_zoomed_end = frame_out
                # hold_n: a genuine hold on the last real frame reached —
                # see the comment above on why this doesn't re-capture
                # more (identical-looking) pydeck frames.
                for _ in range(hold_n):
                    video.write(frame_out)
                dynamic_final_hold = frame_out
                self.last_frame = frame_out
                # highlight_bg only needs to stay non-None here so the
                # `if highlight_bg is None` gate below skips the
                # static-tile fallback path — its actual pixel content is
                # never read again once dynamic_final_hold is set.

        if highlight_bg is None:
            # Either dynamic pydeck wasn't requested, or it failed —
            # original path: a genuinely higher-zoom SEPARATE image,
            # fetched fresh, cut to after a lead-in push on the wide map.
            fetched = self._fetch_highlight_image(
                lat, lng, (w, h), next_lat=next_lat, next_lon=next_lon
            )
            if not fetched:
                return False
            highlight_path, highlight_extent = fetched
            highlight_bg = self.graphics.read_image_safe(highlight_path)
            if highlight_bg is None:
                return False
            if highlight_bg.shape[:2] != (h, w):
                highlight_bg = cv2.resize(highlight_bg, (w, h))

            px, py = RouteGeometryProcessor.project_latlon_to_pixel(
                lat, lng, highlight_extent, w, h
            )
            px, py = int(px), int(py)

            # The close-up tile is genuinely zoomed in, but at this scale a
            # nearby waypoint can easily fall inside the same small area —
            # without this they'd be invisible even though they're physically
            # on screen. Drawn with the same S/E/stop-by/number labeling as
            # everywhere else, so a stop that happens to land in frame reads
            # exactly like it does on the main overview map.
            self._draw_route_line_on_extent(highlight_bg, w, h, highlight_extent)
            self._draw_nearby_waypoints(highlight_bg, w, h, highlight_extent, px, py)

            # Lead-in: push in on the clean map plate (no cards on it — see
            # the docstring above), toward the same point, BEFORE cutting to
            # the close-up tile — this is the "zoom from the big map" half
            # of the beat; the cut below and the _ken_burns_hold after it
            # are the "into the waypoint start" half.
            lead_in_source = clean_map_frame if clean_map_frame is not None else self.last_frame
            self.last_frame = self._ken_burns_hold(
                video, lead_in_source, fps, self._BIG_MAP_ZOOM_LEAD_SECONDS,
                featured_popup["x"], featured_popup["y"],
                zoom_from=1.0, zoom_to=self._BIG_MAP_ZOOM_TARGET,
            )

        if dynamic_final_hold is not None:
            # The dynamic pydeck path already built highlight_popup,
            # composited it onto every frame, and wrote the whole beat
            # (lead-in + wait + hold, as applicable) to `video` — nothing
            # left to draw or digitally zoom here, just hand the right
            # endpoint frames to whichever branch below needs them.
            zoomed_end = dynamic_zoomed_end if dynamic_zoomed_end is not None else dynamic_final_hold
            highlight_frame = dynamic_final_hold
        else:
            highlight_popup = featured_popup.copy()
            highlight_popup["data"] = featured_popup["data"].copy()
            highlight_popup["x"], highlight_popup["y"] = px, py
            # render_popup_box's leader line prefers "pin_x"/"pin_y" over
            # "x"/"y" when present (see pins.py's declutter fan-out) — a
            # leftover fanned-out position from the main overview render,
            # in that image's own coordinate space, means nothing on this
            # freshly fetched close-up tile. Without clearing it here the
            # leader line anchors on that stale spot instead of the
            # marker actually drawn at (px, py) above.
            highlight_popup.pop("pin_x", None)
            highlight_popup.pop("pin_y", None)
            # Same reasoning as the dynamic-pydeck branch above: this is
            # still the SAME dict the recap just stamped its own
            # (typically shrunk, packing-many-cards) "card_scale" and
            # frame-specific "beside_box"/"leader_via"/"recap_line_color"
            # onto — cleared so the highlight's card sizes and positions
            # itself fresh instead of rendering at whatever fraction the
            # recap needed.
            for _stale_key in ("card_scale", "beside_box", "leader_via", "recap_line_color"):
                highlight_popup.pop(_stale_key, None)
            highlight_popup["hud_corner"] = None  # forces the leader-lined "beside" card style
            highlight_popup["draw_leader_line"] = True
            # Same short-leader-line placement flow-through popups use
            # elsewhere (starts ~55px from the pin, spiraling out only if
            # that spot's taken) — without this, render_popup_box's own
            # fallback placement (meant for corner-avoidance, not a tight
            # leader line) can land the card far across the frame.
            self._layout_recap_popups([{"popup": highlight_popup, "frames_left": 1}], w, h)
            # The photo sits on top of its pin (the free layout can hang it below).
            self._place_cards_above_pins([highlight_popup], w, h, *self.graphics.beside_card_footprint())

            # Line, then marker, then card — in that order — so the
            # leader line sits BEHIND both the marker pin and the card it
            # connects, instead of potentially drawing on top of the pin
            # (drawing the marker first, as before, put the line above it
            # whenever render_popup_box ran afterward).
            highlight_bg = self.graphics.render_popup_box(
                highlight_bg, highlight_popup, line_only=True
            )
            self.graphics.draw_marker(
                highlight_bg, px, py,
                number="S" if is_start else "E",
                color=self._START_PIN_COLOR if is_start else self._END_PIN_COLOR,
                image=highlight_popup["data"].get("pin_image"),
            )
            highlight_frame = self.graphics.render_popup_box(
                highlight_bg, highlight_popup, skip_line=True
            )

            # Hard cut straight to the highlight — no transition
            # connecting the two shots — then a slow Ken Burns zoom-in
            # while it's held, toward the same point (featured_popup's
            # own x/y, untouched by highlight_popup's copy above, which
            # overwrites its OWN x/y with px/py in the new highlight
            # image's space) rather than a static freeze. Only reached
            # when the dynamic pydeck path wasn't used/failed — see the
            # branch above.
            zoomed_end = self._ken_burns_hold(
                video, highlight_frame, fps, self._ENDING_HIGHLIGHT_WAIT_SECONDS,
                featured_popup["x"], featured_popup["y"],
                zoom_from=1.0, zoom_to=1.18,
            )
            self.last_frame = zoomed_end

        if dynamic_final_hold is None:
            # Continue the same zoom further rather than resetting to a
            # static hold — one continuous push for the whole highlight
            # beat instead of a moving bit followed by a frozen bit. Only
            # reached on the static-tile fallback path — the dynamic
            # pydeck path already wrote this hold's frames as real
            # re-renders (see the capture loop above) and already set
            # self.last_frame to the last one.
            self.last_frame = self._ken_burns_hold(
                video, highlight_frame, fps, highlight_hold_sec,
                featured_popup["x"], featured_popup["y"],
                zoom_from=1.18, zoom_to=1.35,
            )

        if is_fullscreen:
            # The narration has ended by now (the pip hold above covered it):
            # the photo grows to fullscreen, holds briefly and blurs out.
            scale_sec = self.transition_cfg["scale_seconds"]
            hold_sec = self.transition_cfg["min_hold_seconds"]
            tail_start = video.frames_written
            t_frames = self.graphics.generate_fullscreen_popup_transition(
                base_frame=self.last_frame,
                popup_info=highlight_popup,
                fps=fps,
                duration_sec=scale_sec,
                hold_sec=hold_sec,
                fade_out_sec=self.transition_cfg["fade_out_seconds"],
            )
            if t_frames:
                # Drop the trailing fade-BACK-to-the-map portion — this
                # fullscreen photo is meant to be the video's actual last
                # frame, not a cutaway that returns to the map afterward.
                keep = max(1, int(scale_sec * fps)) + max(1, int(hold_sec * fps))
                t_frames = t_frames[:keep]
                for transition_frame in t_frames:
                    video.write(transition_frame)

                # Blur out rather than hard-cutting on the photo — a bare
                # cut here would jump straight into whatever plays next;
                # softening out of focus first reads smoothly even when
                # the next clip opens on this exact same picture.
                self.last_frame = self._blur_out(video, t_frames[-1], fps)
                # Plays after the voice, so not part of the audio/video match.
                self.ending_tail_seconds = (video.frames_written - tail_start) / fps
                return True
        return False
