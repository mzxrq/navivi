"""Cut/fade and blur-out transition primitives, plus the end-of-video recap,
summary card, and higher-zoom "callback to where the journey began" highlight."""

import math
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter
from services import tuning

from .base import logger


class _TransitionMixin:
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
        n = max(1, int(duration_sec * fps))
        last = frame
        for i in range(n):
            progress = i / max(1, n - 1)
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
        n = max(1, int(duration_sec * fps))
        max_ksize = max(3, (min(frame.shape[:2]) // 20) | 1)  # odd, ~5% of the short edge
        blurred = frame
        for i in range(n):
            ksize = max(1, round((i + 1) / n * max_ksize)) | 1
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
        """Builds the end-of-video recap (every waypoint's card at once,
        each with a leader line back to its own pin) if there's a
        stop_popup, fades the summary stat card in on top of it, and
        returns how long (seconds) the caller should hold on the result
        before moving on — the longer of the recap's own freeze_seconds
        and the summary card's configured hold, so the two read as one
        continuous ending beat rather than the recap being shown alone
        first and the card only appearing afterward in its own pause.
        Updates self.last_frame; does not write the hold itself, since
        the highlight (_render_ending_highlight) may still need to run
        first."""
        outro_hold_sec = 0.0

        if stop_popup:
            # Clean plate (see pre_popup_frame's own comment above) rather
            # than self.last_frame, which can still have a not-yet-finished
            # popup fade-out baked into it — and it already has every
            # numbered pin drawn on it, so the recap doesn't need to
            # redraw them. The end waypoint's own image_display
            # ("fullscreen"/"pip") is honored later, by
            # _render_ending_highlight AFTER the zoom-to-higher-tile
            # transition — never here.
            outro_frame = (
                pre_popup_frame.copy() if pre_popup_frame is not None
                else self.last_frame.copy()
            )
            self.last_frame = self._render_recap_frame(
                outro_frame, active_popups, w, h,
                route_obstacles=route_obstacle_arr,
                reserved_boxes=reserved_boxes,
            )
            outro_hold_sec = float(stop_popup["data"].get("freeze_seconds", 3.0))

        if summary_card is not None:
            fade_frames = max(1, int(self.config.get("summary_fade", 0.5) * fps))
            for i in range(fade_frames):
                video.write(
                    self.graphics.composite_card_on_frame(
                        self.last_frame, summary_card, alpha=(i + 1) / fade_frames
                    )
                )
            self.last_frame = self.graphics.composite_card_on_frame(
                self.last_frame, summary_card, alpha=1.0
            )
            outro_hold_sec = max(
                outro_hold_sec, float(self.config.get("summary_hold", 4.0))
            )

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
            is_stopby = bool(jw.get("isStopBy", False))
            if not is_stopby:
                order += 1
            lat, lng = jw.get("lat"), jw.get("lng", jw.get("lon"))
            if lat is None or lng is None:
                continue
            px, py = RouteGeometryProcessor.project_latlon_to_pixel(lat, lng, extent, w, h)
            px, py = int(px), int(py)
            if not (0 <= px <= w and 0 <= py <= h):
                continue
            if math.hypot(px - exclude_px, py - exclude_py) < self.graphics.marker_radius * 2:
                continue  # the featured waypoint itself
            # "arrived": True — this only ever runs at the very end of
            # the video, once the whole route (every waypoint) has
            # genuinely been visited, so every pin here should show its
            # own arrived_marker_color, same as it does for the rest of
            # the video, rather than falling back to the DEFAULT
            # (not-yet-visited) marker_color — visibly wrong whenever a
            # project has customized the two to different colors.
            wp = {"index": pos + 1, "order": order, "data": {"is_stopby": is_stopby, "arrived": True}}
            label, color = self._pin_label_and_color(wp, total_points)
            self.graphics.draw_marker(frame, px, py, number=label, color=color)

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
        which case the caller's normal trailing pause still applies."""
        job_config = self._get_job_config() or {}
        is_start = bool(job_config.get("start_point"))
        zoom_point = job_config.get("start_point") or job_config.get("end_point") or {}
        lat, lng = zoom_point.get("lat"), zoom_point.get("lng")
        if lat is None or lng is None:
            return False

        featured_popup = start_popup or stop_popup
        settings = (job_config.get("settings", {}) or {})
        # "enable_gl_ending_zoom" — the actual job_config.json setting
        # this feature is toggled by (also honors overview_background:
        # "pydeck" as an alternate opt-in, since a project already using
        # pydeck for its overview background naturally wants this too).
        use_dynamic_pydeck = bounding_box is not None and (
            bool(settings.get("enable_gl_ending_zoom", False))
            or str(settings.get("overview_background", "")).lower() == "pydeck"
        )
        is_fullscreen = (
            self.enable_fullscreen_popups
            and featured_popup["data"].get("image_display") == "fullscreen"
        )
        highlight_hold_sec = float(featured_popup["data"].get("freeze_seconds", 3.0))

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
                hold_n = 0 if is_fullscreen else max(1, int(highlight_hold_sec * fps))
                zoom_n = lead_in_n + wait_n

                dynamic_frames = capture_pydeck_zoom_sequence(
                    bounding_box, (w, h), lat, lng, zoom_n,
                    zoom_boost=tuning.ENDING_HIGHLIGHT_PYDECK_ZOOM_BOOST,
                    mapbox_key=settings.get("mapbox_token"),
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
                highlight_popup["hud_corner"] = None
                highlight_popup["draw_leader_line"] = True
                self._layout_beside_popups([{"popup": highlight_popup, "frames_left": 1}], w, h)

                for i, (frame_bgr, extent) in enumerate(dynamic_frames):
                    frame_out = frame_bgr.copy()
                    # Nearby waypoints re-projected fresh against THIS
                    # frame's own extent (it changes every frame as the
                    # camera zooms), unlike the featured marker/card
                    # above, which stays pixel-fixed by construction.
                    # _draw_nearby_waypoints deliberately EXCLUDES the
                    # featured point itself (px, py) — it's meant to be
                    # drawn separately below — so without drawing its own
                    # marker unconditionally here too, the start/end pin
                    # was simply missing from every lead-in frame.
                    self._draw_nearby_waypoints(frame_out, w, h, extent, px, py)
                    if i < lead_in_n:
                        self.graphics.draw_marker(
                            frame_out, px, py,
                            number="S" if is_start else "E",
                            color=self._START_PIN_COLOR if is_start else self._END_PIN_COLOR,
                        )
                    if i >= lead_in_n:
                        # The "hard cut to arrived" moment — before this
                        # frame the featured point is just a plain pin on
                        # the map, same as every other waypoint (matches
                        # the static-tile fallback's own lead-in, which
                        # shows no card either); from here on its
                        # leader-lined card joins it too.
                        frame_out = self.graphics.render_popup_box(
                            frame_out, highlight_popup, line_only=True
                        )
                        self.graphics.draw_marker(
                            frame_out, px, py,
                            number="S" if is_start else "E",
                            color=self._START_PIN_COLOR if is_start else self._END_PIN_COLOR,
                        )
                        frame_out = self.graphics.render_popup_box(
                            frame_out, highlight_popup, skip_line=True
                        )
                    video.write(frame_out)
                    if i == lead_in_n + wait_n - 1:
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
            fetched = self._fetch_highlight_image(lat, lng, (w, h))
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
            highlight_popup["hud_corner"] = None  # forces the leader-lined "beside" card style
            highlight_popup["draw_leader_line"] = True
            # Same short-leader-line placement flow-through popups use
            # elsewhere (starts ~55px from the pin, spiraling out only if
            # that spot's taken) — without this, render_popup_box's own
            # fallback placement (meant for corner-avoidance, not a tight
            # leader line) can land the card far across the frame.
            self._layout_beside_popups([{"popup": highlight_popup, "frames_left": 1}], w, h)

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

        if is_fullscreen:
            scale_sec = self.transition_cfg["scale_seconds"]
            hold_sec = self.transition_cfg["min_hold_seconds"]
            t_frames = self.graphics.generate_fullscreen_popup_transition(
                base_frame=zoomed_end,
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
                for tf in t_frames:
                    video.write(tf)

                # Blur out rather than hard-cutting on the photo — a bare
                # cut here would jump straight into whatever plays next;
                # softening out of focus first reads smoothly even when
                # the next clip opens on this exact same picture.
                self.last_frame = self._blur_out(video, t_frames[-1], fps)
                return True
        elif dynamic_final_hold is None:
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
        return False
