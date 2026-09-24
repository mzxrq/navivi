"""The overview map render entry point: sets up the route (labels, speed-
weighted path, intro beat), delegates the frame-by-frame animation to
_OverviewAnimationMixin, then closes out with the recap/summary/ending
highlight. The mode-breakpoint/path-pacing helpers live in
overview_pacing.py and the animation loop itself in overview_animation.py —
both split out of this file to keep it to the setup/wrap-up orchestration."""

import json
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services import tuning
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter

from .base import logger

# Overview render tuning constants (magic numbers pulled out of the setup
# logic below so their purpose has a name; none of these are read from
# self.config/tuning, they're just fixed constants of this render).
_MIN_OVERVIEW_FRAMES = 10  # floor on num_frames even for a very short duration
_ROUTE_LATLON_SAMPLE_STRIDE = 500  # decimation stride for self._route_latlon_path
_ROUTE_OBSTACLE_MAX_POINTS = 400  # cap on the decimated obstacle array's size
_MIN_LEG_DISPLAY_SECONDS = 1.5  # floor on a flow-through popup's own leg_display_seconds
_EXPECTED_FRAME_SEARCH_MARGIN_MIN_FRAMES = 20  # floor on the expected-frame search window
_EXPECTED_FRAME_SEARCH_FRACTION = 0.05  # window size as a fraction of the path's frame count
_DEFAULT_INTRO_FREEZE_SECONDS = 3.0  # used when the start popup sets no freeze_seconds
_INTRO_CLEAN_HOLD_FRACTION_OF_FREEZE = 0.5  # clean-beat hold, as a fraction of intro_freeze_sec


class _OverviewRenderMixin:
    def render_overview(
        self,
        bg_path: str,
        points: List,
        labels: List,
        popups: List,
        fps: int,
        summary: Optional[Dict] = None,
        point_modes: Optional[List[str]] = None,
        bounding_box: Optional[Dict[str, float]] = None,
        extent: Optional[Tuple[float, float, float, float]] = None,
    ) -> str:
        is_video = False

        if is_video:
            cap = cv2.VideoCapture(str(bg_path))
            ret, current_bg = cap.read()
            if not ret:
                raise FileNotFoundError(f"Cannot read video frames from: {bg_path}")
        else:
            current_bg = self.graphics.read_image_safe(str(bg_path))
            if current_bg is None:
                raise FileNotFoundError(f"Cannot read background image: {bg_path}")
            cap = None

        h, w = current_bg.shape[:2]
        if h % 2 != 0 or w % 2 != 0:
            h, w = h - (h % 2), w - (w % 2)
            current_bg = cv2.resize(current_bg, (w, h))

        duration = self.config.get("duration", 30.0)
        num_frames = max(_MIN_OVERVIEW_FRAMES, int(duration * fps))

        start_label, end_label = "開始", "終点"
        for ancestor_dir in [self.out_dir] + list(self.out_dir.parents):
            potential_path = ancestor_dir / "job_config.json"
            if potential_path.exists():
                try:
                    with open(potential_path, "r", encoding="utf-8") as f:
                        job_data = json.load(f)
                        start_label = job_data.get("start_point", {}).get(
                            "label", start_label
                        )
                        end_label = job_data.get("end_point", {}).get(
                            "label", end_label
                        )
                except Exception:
                    pass
                break

        cleaned_labels = []
        for i, lbl in enumerate(labels):
            if i == 0:
                cleaned_labels.append(start_label)
            elif i == len(points) - 1:
                cleaned_labels.append(end_label)
            else:
                cleaned_labels.append(
                    lbl.replace(tuning.PIPELINE_LABELS["start_prefix"], "")
                    .replace(tuning.PIPELINE_LABELS["stop_prefix"], "")
                    .replace(tuning.PIPELINE_LABELS["start_prefix"].strip(": "), "")
                    .replace(tuning.PIPELINE_LABELS["stop_prefix"].strip(": "), "")
                    .strip()
                    if lbl
                    else None
                )


        smooth_path, mode_breakpoints, cum_smooth_dist, total_smooth_dist = (
            self._build_overview_path(points, point_modes, num_frames)
        )

        # Stashed so _render_ending_highlight can redraw the route line on
        # its own, freshly fetched close-up tile (a different extent than
        # this wide overview map) — reprojected from this animated path's
        # own pixel coordinates back to lat/lon via THIS render's extent,
        # since that's the only extent this pixel data is meaningful
        # against. None when extent wasn't given (falls back to no line
        # drawn on the highlight, same as before this existed).
        self._route_latlon_path = (
            [
                RouteGeometryProcessor.pixel_to_latlon(p[0], p[1], extent, w, h)
                for p in smooth_path[:: max(1, len(smooth_path) // _ROUTE_LATLON_SAMPLE_STRIDE)]
            ]
            if extent is not None
            else None
        )

        active_popups = [
            {
                "x": points[i][0],
                "y": points[i][1],
                "data": popups[i],
                "label": cleaned_labels[i],
                "index": i,
            }
            for i in range(len(points))
            if popups and popups[i] is not None
        ]

        # Every waypoint's "x"/"y" above came from points[i] — the nearest
        # point on the RECORDED TRACK, not its own true coordinate. That's
        # visibly wrong for a stop-by only ever observed from a distance
        # (a small offshore island seen from the trail, a viewpoint across
        # the water) — it can sit well away from the track entirely, and
        # snapping it onto the nearest track pixel used to draw its pin
        # right on top of the route line instead of at the real place. But
        # it's ALSO measurably off for a genuinely-visited real waypoint:
        # the recorded/routed track is a sparse polyline (points sampled
        # every so often, or snapped to a road centerline by the routing
        # API), so the nearest track pixel to a real POI's true coordinate
        # can land a visible distance from where that place actually is —
        # a station pin sitting on the road instead of the station
        # building, say. Re-projecting every waypoint from its own stored
        # lat/lng (see render_step.py's route_popups) onto this same
        # background image draws each one exactly where it really is,
        # rather than only wherever the track happened to pass closest.
        if extent is not None:
            for ap in active_popups:
                lat, lng = ap["data"].get("lat"), ap["data"].get("lng")
                if lat is None or lng is None:
                    continue
                px, py = RouteGeometryProcessor.project_latlon_to_pixel(
                    lat, lng, extent, w, h
                )
                ap["x"], ap["y"] = px, py

        # 1-based visit order, used to number each waypoint's pin and to
        # sort concurrently-visible popups in _layout_beside_popups. Stop-by
        # waypoints are skipped from the count (they show a "・" dot instead
        # of a number — see pins.py's _draw_pin) — matches the map editor's
        # own MapArea.tsx normalIndex, which only increments for waypoints
        # that aren't isStopBy.
        order = 0
        for ap in active_popups:
            # The route's literal start ("S", index 0) isn't part of the
            # visible 1..N numbering either — same treatment as a stop-by,
            # just for a different reason (it's labeled "S" outright, see
            # pins.py's _pin_label_and_color). Without this, S consumed
            # order 1 for itself, pushing every real numbered waypoint one
            # higher than its actual visit order (the first real stop
            # showing "2" instead of "1").
            if ap["data"].get("is_stopby") or ap["index"] == 0:
                # Still gets an "order" key (just not incremented) so it's
                # never missing when something reads ap["order"] generically
                # — excluded only from the visible count/numbering itself.
                ap["order"] = order
                continue
            order += 1
            ap["order"] = order

        # Which stop-bys ride along with which stop. An unconnected
        # stop-by is a place the traveler never actually goes, so it's
        # shown during the previous NORMAL waypoint's stop rather than
        # popping where it sits; a "Connect to Route" one is a genuine
        # stop and keeps its own arrival. See _attach_stopby_groups.
        self._attach_stopby_groups(active_popups)

        # Pins that would be drawn completely on top of each other are
        # nudged just far enough apart to both stay visible — a tight
        # cluster of stops (four stop-by landmarks around one small town,
        # say) otherwise shows as three dots for four waypoints, the last
        # one painted hiding the rest.
        #
        # This pass used to fan a whole cluster out onto a circle around
        # its shared centre, which moved pins clear off the route line
        # they sit on ("this stop isn't really on the path") and was
        # disabled outright for that reason. It now only separates pins
        # whose drawn silhouettes actually collide, by the minimum amount
        # needed and within a hard cap on how far any one pin may travel
        # from its true position, so nothing drifts off-route — see
        # pins.py's _declutter_pins.
        self._declutter_pins(active_popups)

        # Popup card border matches this waypoint's own pin color (S=green,
        # E=red, stop-by=brown, everything else=the default marker color)
        # — set once here, on the source active_popups entries, rather
        # than at every individual card-building call site downstream,
        # since virtually all of them start from a .copy() of one of
        # these and would otherwise need to recompute/thread it through
        # separately.
        total_points_for_color = len(points)
        for ap in active_popups:
            _, pin_color_for_border, _ = self._pin_label_and_color(ap, total_points_for_color)
            # _pin_label_and_color can return None for a plain numbered pin
            # not yet "arrived" (see _pin_color) — fall back to the base
            # marker color rather than letting popup_box's border draw
            # None through.
            ap["border_color"] = pin_color_for_border or self.graphics.marker_color

        # job_config.json's own "waypoints" array here already includes the
        # route's start (index 0) and end (its last index) as real entries
        # in their own right (render_step.py's own waypoint-injection loop
        # special-cases idx==0/idx==len(waypoints)-1 for their labels, but
        # still builds a popup entry for them the same as every other
        # waypoint) — so it lines up 1:1, in the same order, with
        # `active_popups` (built by filtering that SAME per-waypoint
        # `popups` array route_step.py produced). A previous version of
        # this loop assumed job_waypoints excluded start/end (true for a
        # DIFFERENT reader — see waypoints.py/transitions.py's
        # _draw_nearby_waypoints, which reads job_config's start_point/
        # end_point directly instead) and shifted by `popup["index"] - 1"
        # — but `popup["index"]` here is a position in the raw, thousands-
        # of-points-long animated path, not a small 0..N waypoint count, so
        # that shift missed the bounds check for virtually every waypoint
        # beyond the first few, silently skipping this whole block (no
        # freeze_frame/image_display/popup_video override ever applied)
        # for most of the route. Zipping by enumerate() position instead —
        # matching active_popups' own build order to job_waypoints' — is
        # what actually lines each waypoint up with its own config entry.
        job_waypoints = self._get_job_waypoints()
        for i, popup in enumerate(active_popups):
            if i < len(job_waypoints):
                jw = job_waypoints[i]
                if (
                    "image_display" in jw
                    and popup["data"].get("image_display", "box") == "box"
                ):
                    popup["data"]["image_display"] = jw["image_display"]
                if "popup_video" in jw and not popup["data"].get("popup_video"):
                    popup["data"]["popup_video"] = jw["popup_video"]
                # Waypoints flow through by default (the traveler never
                # stops, all the way to the end) — set "freeze_frame": true
                # on a waypoint in job_config.json to opt IT back into the
                # old held-frame arrival pause. Flow-through popup cards
                # ride along beside the pin (see _layout_beside_popups)
                # rather than holding the frame.
                if "freeze_frame" in jw:
                    popup["data"]["freeze_frame"] = bool(jw["freeze_frame"])

        # Static footprint (the full route line + every pin) used to pick a
        # HUD corner that the popup card won't sit on top of. Computed once
        # from the whole route rather than the animated path-so-far, so a
        # given waypoint's card always lands in the same corner regardless
        # of when in the animation it triggers.
        # pin_x/pin_y (set to each popup's real x/y by _declutter_pins) —
        # kept as the lookup key rather than x/y directly so this stays
        # correct if a future declutter pass ever nudges pins apart again.
        route_avoid_points = list(points) + [
            (p.get("pin_x", p["x"]), p.get("pin_y", p["y"])) for p in active_popups
        ]

        # Same footprint, as a decimated numpy array — lets
        # _layout_beside_popups check a candidate card position against the
        # route line itself (cheaply, vectorized) so a flow-through card
        # doesn't get planted right on top of the path it's next to.
        route_obstacle_arr = np.asarray(route_avoid_points, dtype=float)
        if len(route_obstacle_arr) > _ROUTE_OBSTACLE_MAX_POINTS:
            step = max(1, len(route_obstacle_arr) // _ROUTE_OBSTACLE_MAX_POINTS)
            route_obstacle_arr = route_obstacle_arr[::step]

        # Pin centers alone under-protect each waypoint's drawn silhouette
        # (see _pin_obstacle_points) — without this, a flow-through card
        # can be placed over a neighbouring pin's teardrop/halo during the
        # animated phase and, since cards composite after pins every frame,
        # visually erase that waypoint marker for as long as it's shown.
        pin_obstacles = self._pin_obstacle_points(active_popups)
        if len(pin_obstacles):
            route_obstacle_arr = np.vstack([route_obstacle_arr, pin_obstacles])

        logger.info(f"Rendering Overview Map ({duration}s)")
        overview_path = str(self.out_dir / "01_overview.mp4")
        video = VideoExporter(overview_path, w, h, fps)

        intro_frame = current_bg.copy()
        start_popup = next((p for p in active_popups if p["index"] == 0), None)
        stop_popup = next(
            (p for p in active_popups if p["index"] == len(points) - 1), None
        )

        # A flow-through popup's display duration defaults to a fixed
        # freeze_seconds regardless of how long that leg of the route
        # actually takes to animate — so on a short leg the NEXT waypoint's
        # popup could trigger while the previous one is still showing, and
        # on a long leg it could vanish long before the traveler arrives.
        # Instead, tie it to the leg itself: find each waypoint's own
        # expected frame (nearest point along the animated path) and set
        # its popup to last exactly from there until the next waypoint's
        # expected frame — "2 to 3" shows popup 2, and the moment 3 is
        # reached popup 2 hides and popup 3 takes over.
        smooth_arr_lookup = np.asarray(smooth_path, dtype=float)
        num_frames_lookup = len(smooth_arr_lookup)

        # Each original waypoint's own fraction of the route's real
        # physical distance (start-to-waypoint / start-to-end), over the
        # raw waypoint polyline — independent of any curve shape, so a
        # route that loops or self-crosses doesn't affect it at all.
        raw_seg = np.hypot(
            np.diff([p[0] for p in points]), np.diff([p[1] for p in points])
        )
        raw_cum = np.concatenate([[0.0], np.cumsum(raw_seg)])
        raw_total = raw_cum[-1] if raw_cum[-1] > 0 else 1.0

        def _estimate_frame(point_index: int) -> int:
            # cum_smooth_dist is the ANIMATED path's own cumulative real
            # pixel distance per frame (already speed-weighted per mode —
            # see _build_overview_path) — searching it for this
            # waypoint's target distance is a pure 1D lookup along "how
            # far traveled", with no notion of XY position at all, so it
            # can't be fooled by the curve merely passing physically
            # close to some OTHER point earlier on. Falls back to a
            # straight frame-count fraction when there's no mode data to
            # have produced cum_smooth_dist in the first place.
            frac = raw_cum[point_index] / raw_total
            if cum_smooth_dist is not None:
                target_dist = frac * total_smooth_dist
                return int(np.searchsorted(cum_smooth_dist, target_dist))
            return int(frac * (num_frames_lookup - 1))

        def _expected_frame(px: float, py: float, search_from: int, search_to: int) -> int:
            window = smooth_arr_lookup[search_from:search_to + 1]
            if len(window) == 0:
                return search_from
            dists = np.hypot(window[:, 0] - px, window[:, 1] - py)
            return search_from + int(np.argmin(dists))

        # Each waypoint's own true position in the path's time-sequence —
        # not just "is the traveler's dot pixel-close to this pin right
        # now", which a route that loops or doubles back near a pin
        # before actually reaching it (see the proximity-trigger gate in
        # _animate_overview_frames) could satisfy far too early, popping
        # the card up for a waypoint the traveler hasn't really arrived
        # at yet — just passed near on an earlier, unrelated stretch of
        # road.
        #
        # _estimate_frame (distance-based, immune to self-crossing) picks
        # the anchor; the nearest-XY search below only fine-tunes within a
        # small window around that anchor, rather than searching the
        # whole remaining path — an open-ended forward search still let a
        # route that loops back close to a LATER waypoint's pin before
        # actually reaching it grab that closer-but-wrong crossing
        # (reported: waypoint 7's card appearing while the traveler was
        # still passing near the END pin's location first). Clamped to
        # never go before the previous waypoint's own match, same
        # guarantee as before.
        last_matched_frame = 0
        search_margin = max(
            _EXPECTED_FRAME_SEARCH_MARGIN_MIN_FRAMES,
            int(num_frames_lookup * _EXPECTED_FRAME_SEARCH_FRACTION),
        )
        for ap in active_popups:
            if ap["index"] == 0:
                ap["expected_frame"] = 0
                continue
            est = max(last_matched_frame, min(num_frames_lookup - 1, _estimate_frame(ap["index"])))
            window_from = max(last_matched_frame, est - search_margin)
            window_to = min(num_frames_lookup - 1, est + search_margin)
            ef = _expected_frame(ap["x"], ap["y"], window_from, window_to)
            ap["expected_frame"] = ef
            last_matched_frame = ef

        triggerable = [
            ap for ap in active_popups
            if ap["index"] != 0 and (not stop_popup or ap["index"] != stop_popup["index"])
        ]
        triggerable.sort(key=lambda ap: ap["expected_frame"])
        stop_expected_frame = stop_popup["expected_frame"] if stop_popup else None
        min_leg_frames = int(fps * max(_MIN_LEG_DISPLAY_SECONDS, tuning.POPUP_MIN_DISPLAY_SECONDS))
        # Capped at the same POPUP_FREEZE_SECONDS_MAX ceiling every other
        # popup display duration in this file is bounded by — without it,
        # the LAST triggerable waypoint before a long uninterrupted stretch
        # back to the final destination (a "return leg" with no stops of
        # its own) gets next_frame = stop_expected_frame, at the very end
        # of the whole video: its card's display time would span that
        # entire remaining stretch instead of a normal few-second flash,
        # reported as an old waypoint's popup still sitting on screen deep
        # into the return leg.
        max_leg_frames = int(fps * tuning.POPUP_FREEZE_SECONDS_MAX)
        # The top banner starts anticipating the NEXT waypoint ("まもなく
        # ...") this many seconds before it's actually reached (see
        # OVERVIEW_BANNER_NEAR_SECONDS in the main animation loop) — a
        # popup sized to last right up until that next waypoint's own
        # expected_frame would still be on screen for the whole length of
        # that anticipation window, visibly overlapping the "まもなく
        # <next place>" banner with THIS waypoint's own card. Subtracting
        # it here means the card finishes (fade-out included) before that
        # banner even appears. This got noticeably more visible once
        # walking's own on-screen pace slowed down (see
        # tuning.WALKING_ANIMATION_SPEED_FACTOR): the same real leg now
        # spans more animated frames, so the fixed anticipation window
        # covers proportionally more of a walking leg's own popup display
        # than it used to.
        banner_near_frames = int(fps * tuning.OVERVIEW_BANNER_NEAR_SECONDS)
        for i, ap in enumerate(triggerable):
            this_frame = ap["expected_frame"]
            next_frame = (
                triggerable[i + 1]["expected_frame"]
                if i + 1 < len(triggerable)
                else stop_expected_frame
            )
            if next_frame is not None:
                raw_gap = next_frame - banner_near_frames - this_frame
                ap["leg_display_seconds"] = (
                    min(max_leg_frames, max(min_leg_frames, raw_gap)) / fps
                )


        intro_freeze_sec = _DEFAULT_INTRO_FREEZE_SECONDS
        if start_popup and "freeze_seconds" in start_popup["data"]:
            # Floored at POPUP_MIN_DISPLAY_SECONDS, same as every other
            # freeze_seconds read (see popups.py's own floor) -- this one
            # reads job_config's raw value directly rather than going
            # through that shared display path, so it needs its own floor.
            intro_freeze_sec = max(
                float(start_popup["data"]["freeze_seconds"]), tuning.POPUP_MIN_DISPLAY_SECONDS
            )

        if start_popup:
            intro_card_scale = self.config.get("overview_intro_card_scale", 1.3)
            footprint_w, footprint_h = self.graphics.beside_card_footprint(intro_card_scale)

            def _make_intro_card(popup: Dict) -> Dict:
                card = popup.copy()
                card["data"] = popup["data"].copy()
                card["card_scale"] = intro_card_scale
                # card_scale alone made the caption grow right along with
                # the photo — fine for the photo (that's the point of
                # intro_card_scale), but the label text read as oversized
                # (and wrapped to two lines more readily) well past what
                # a normal flow-through card's caption looks like. Scaled
                # back down independently of the photo/card size.
                card["label_font_scale"] = self.config.get(
                    "overview_intro_label_font_scale", 0.7
                )
                return card

            temp_sp = _make_intro_card(start_popup)
            # Both the start AND stop waypoint's own photo (when it has
            # one — most routes set popup_image on every waypoint incl.
            # the destination) are previewed together on the intro, rather
            # than only ever revealing the destination at the very end.
            # A loop route's "E" is the exact same real-world place as "S"
            # (see SpatialRendererBase._is_loop_route) though — showing
            # both there would just duplicate the start card's own photo
            # right next to itself, so it's skipped (same reasoning as
            # transitions.py's end-of-video recap, which drops the same
            # duplicate popup for the same reason).
            temp_ep = (
                _make_intro_card(stop_popup)
                if stop_popup
                and stop_popup["data"].get("popup_image")
                and not self._is_loop_route
                else None
            )
            intro_cards = [temp_sp] + ([temp_ep] if temp_ep else [])

            # Anchored beside their own pin with a leader line back to it
            # (see render_popup_box's non-HUD-corner branch), matching
            # every other waypoint's popup style, rather than a fixed
            # screen corner picked independently of where each pin
            # actually sits. Laid out together (one _layout_beside_popups
            # call) so the start/stop cards can't land on top of each
            # other. A wide search radius, not the ~260px default — these
            # cards sit over the intro's full-route overview, which
            # usually has every waypoint's pin clustered somewhere on
            # screen (as dense a cluster as the S/2/3/E group here); this
            # one-off intro card has no "stay near the traveler" need, so
            # it should keep spiraling outward — using any open area the
            # frame actually has — rather than settling for a nearby spot
            # that overlaps another waypoint's pin.
            self._layout_recap_popups(
                [{"popup": c, "frames_left": 1} for c in intro_cards], w, h,
                card_w=footprint_w, card_h=footprint_h,
                route_obstacles=route_obstacle_arr)
            for c in intro_cards:
                c["hud_corner"] = None
                c["draw_leader_line"] = True

            start_popup["data"]["triggered"] = True
            # Pin-drawing checks in overview_animation.py/pins.py now key
            # off "arrived" (set the instant a waypoint is actually
            # reached) rather than "triggered" (which for every OTHER
            # waypoint only flips once its popup card clears the overview's
            # min-trigger-gap cooldown) — the start pin is "reached" from
            # frame one, so set both here same as "triggered" always was.
            # stop_popup itself is deliberately left untouched — unlike
            # the start pin it hasn't actually been reached yet, its real
            # "arrived" state still only flips at the true end of the
            # route (see overview_animation.py); temp_ep is only ever a
            # preview COPY, not stop_popup itself.
            start_popup["data"]["arrived"] = True

            if not is_video:
                # Show every waypoint marker up front on the intro frame,
                # not just the start point, so the whole route's stops are
                # visible before the animation begins.
                for wp in active_popups:
                    self._draw_pin(intro_frame, wp, len(points))
            clean_frame = intro_frame

            # Clean beat first — just the map and every pin, no popup card
            # yet — so the video opens on the route itself rather than
            # cutting straight to a photo. Held briefly before the start/
            # stop popups slide in below.
            clean_hold_sec = min(
                intro_freeze_sec * _INTRO_CLEAN_HOLD_FRACTION_OF_FREEZE,
                float(self.config.get("overview_intro_clean_hold_seconds", 1.5)),
            )
            for _ in range(int(clean_hold_sec * fps)):
                video.write(clean_frame)

            def _draw_intro_cards(base: np.ndarray, alpha: float) -> np.ndarray:
                # Line, then pin, then card — in that order (mirrors
                # waypoints.py's own leg intro) — so each leader line sits
                # BEHIND every pin instead of drawing the pins first and
                # letting the line (drawn afterward, as part of the card)
                # land on top of them.
                out = base
                for c in intro_cards:
                    out = self.graphics.render_popup_box(out, c, alpha=alpha, line_only=True)
                if not is_video:
                    for wp in active_popups:
                        self._draw_pin(out, wp, len(points))
                for c in intro_cards:
                    out = self.graphics.render_popup_box(out, c, alpha=alpha, skip_line=True)
                return out

            # Slide-up entrance: the start/stop popups ease up into their
            # real spot (from _POPUP_SLIDE_DISTANCE_PX below it) while
            # fading in over POPUP_FADE_SECONDS — same easing every other
            # waypoint's card uses (see _popup_slide_offset_y) — rather
            # than the cards' photos just being present from the very
            # first frame. The intro always opens as plain pip cards,
            # regardless of either waypoint's own image_display setting —
            # "fullscreen" is only ever honored by the end-of-video
            # zoom-tile highlight (_render_ending_highlight), not here.
            base_boxes = [c.get("beside_box") for c in intro_cards]
            bounce_frames = max(1, int(tuning.POPUP_FADE_SECONDS * fps))
            for i in range(bounce_frames):
                # Straight 0->1 ramp for opacity (no fade back OUT — unlike
                # _popup_fade_alpha's own bp shape, this entrance never
                # disappears again) alongside the slide-up offset — the
                # two finish together at i == bounce_frames-1.
                alpha = min(1.0, (i + 1) / bounce_frames)
                slide = self._popup_slide_offset_y(
                    {"total_frames": bounce_frames, "frames_left": bounce_frames - i,
                     "fade_frames": bounce_frames}
                )
                for c, box in zip(intro_cards, base_boxes):
                    if box:
                        c["beside_box"] = (box[0], int(box[1] + slide))
                video.write(_draw_intro_cards(intro_frame, alpha))

            for c, box in zip(intro_cards, base_boxes):
                if box:
                    c["beside_box"] = box
            intro_frame = _draw_intro_cards(intro_frame, 1.0)
            remaining_frames = int(intro_freeze_sec * fps) - int(clean_hold_sec * fps) - bounce_frames
            for _ in range(max(0, remaining_frames)):
                video.write(intro_frame)

            # Slide-down exit: once the animation is about to actually
            # start moving, the preview cards ease back down and fade
            # out — mirrors the entrance above — rather than abruptly
            # cutting straight from "cards on screen" to "traveler moving"
            # with no transition. Ends back on the clean pins-only frame
            # so _animate_overview_frames picks up from the same plain
            # base the intro opened on.
            for i in range(bounce_frames):
                alpha = max(0.0, 1.0 - (i + 1) / bounce_frames)
                slide = self._popup_slide_offset_y(
                    {"total_frames": bounce_frames, "frames_left": i + 1,
                     "fade_frames": bounce_frames}
                )
                for c, box in zip(intro_cards, base_boxes):
                    if box:
                        c["beside_box"] = (box[0], int(box[1] + slide))
                video.write(_draw_intro_cards(clean_frame, alpha))

            # No zoom effect at the very start — the intro closes plainly
            # on the clean pins-only frame, unzoomed, right before the
            # traveler starts moving. The only zoom-toward-the-start-point
            # beat in this video is the dynamic pydeck (or Ken Burns
            # fallback) one at the very END, after the recap/summary card
            # — see _render_ending_highlight.
            self.last_frame = clean_frame

        pre_popup_frame = self._animate_overview_frames(
            video, current_bg, cap, is_video, w, h, fps,
            smooth_path, mode_breakpoints, cum_smooth_dist, total_smooth_dist,
            active_popups, stop_popup, points, route_avoid_points, route_obstacle_arr,
        )

        # Built once, up front, so its exact footprint can be reserved
        # (see reserved_boxes below) before the recap frame lays out its
        # popup cards — otherwise a card could land right where this gets
        # composited over the video in the bottom-right corner, later.
        summary_card = None
        if summary:
            summary_card = self.graphics.render_summary_card(
                distance_km=summary.get("total_distance_km", 0.0),
                duration_seconds=summary.get("total_duration_seconds", 0.0),
                mode_breakdown=summary.get("mode_breakdown"),
                mode_duration=summary.get("mode_duration"),
            )
        summary_card_margin = 20
        reserved_boxes = (
            [
                (
                    w - summary_card.shape[1] - summary_card_margin,
                    h - summary_card.shape[0] - summary_card_margin,
                    float(w - summary_card_margin),
                    float(h - summary_card_margin),
                )
            ]
            if summary_card is not None
            else []
        )

        outro_hold_sec = self._render_recap_and_summary(
            video, stop_popup, summary_card, active_popups, w, h, fps,
            route_obstacle_arr, reserved_boxes, pre_popup_frame,
        )
        for _ in range(int(outro_hold_sec * fps)):
            video.write(self.last_frame)

        hard_ended = False
        if stop_popup and self.config.get("enable_ending_highlight", True):
            hard_ended = self._render_ending_highlight(
                video, w, h, fps, stop_popup, start_popup,
                clean_map_frame=pre_popup_frame,
                bounding_box=bounding_box,
            )

        for p in popups:
            if p:
                p["triggered"] = False
                p["arrived"] = False

        # The fullscreen ending highlight, when it plays, IS the video's
        # last frame — no trailing pause on the map afterward.
        if not hard_ended:
            for _ in range(int(self.config.get("pause", 2.0) * fps)):
                video.write(self.last_frame)

        self.last_ending_hard_ended = hard_ended

        if cap:
            cap.release()
        return video.release(overview_path)
