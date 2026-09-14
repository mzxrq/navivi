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
from scipy.spatial import cKDTree

from services import tuning
from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter

from .base import logger


class _OverviewRenderMixin:
    @staticmethod
    def _compute_loop_shared_mask(
        smooth_path: np.ndarray,
        points: Optional[List] = None,
        point_frames: Optional[List[int]] = None,
    ) -> np.ndarray:
        """For a loop route, flags every point on the animated path that's
        the SECOND (later) visit to a physical spot already passed
        through earlier — i.e. the actual retrace of a stretch that's
        genuinely walked twice (a ferry crossing, a there-and-back spur).
        The FIRST pass over that same stretch stays a normal single line;
        only once the route comes back over it does it switch to the
        dual-stripe look — "double line only happens when we return back
        over the same route", not on the initial way out. See
        tuning.LOOP_SHARED_CORRIDOR_PX (the pixel-distance threshold) and
        LOOP_SHARED_MIN_TIME_FRACTION (how far apart in time two points
        must be before their closeness counts at all — without it, any
        tight bend in a normal one-way path would trivially satisfy the
        distance check against its own immediate neighbors).

        A pair is excluded only when BOTH its points sit within
        LOOP_SHARED_ENDPOINT_EXCLUSION_PX of the route's own start — S
        and E sit on (near-)the same spot BY DEFINITION for a loop route,
        so the very first steps leaving S will always be pixel-close to
        the very last steps arriving at E, even though that's not an
        actually-shared corridor, just S and E happening to coincide.
        This is deliberately narrower than excluding every point near
        either end outright: a point near E can still legitimately pair
        with a genuinely different, far-from-start point earlier in the
        route (e.g. a real street walked past a waypoint on the way out
        AND again on the way back, close to the station but not
        literally at S) — only when the pair's OTHER point is ALSO right
        at the S/E coincidence does it stop counting.

        Returns a boolean array the same length as smooth_path."""
        n = len(smooth_path)
        mask = np.zeros(n, dtype=bool)
        if n >= 3:
            min_gap = max(1, int(n * tuning.LOOP_SHARED_MIN_TIME_FRACTION))
            tree = cKDTree(smooth_path)
            pairs = tree.query_pairs(r=tuning.LOOP_SHARED_CORRIDOR_PX, output_type="ndarray")
            if len(pairs) > 0:
                far_enough = np.abs(pairs[:, 0] - pairs[:, 1]) > min_gap
                idx = pairs[far_enough]
                if len(idx) > 0:
                    start_dists = np.hypot(
                        smooth_path[:, 0] - smooth_path[0, 0],
                        smooth_path[:, 1] - smooth_path[0, 1],
                    )
                    near_start = start_dists < tuning.LOOP_SHARED_ENDPOINT_EXCLUSION_PX
                    both_near_start = near_start[idx[:, 0]] & near_start[idx[:, 1]]
                    idx = idx[~both_near_start]
                    # query_pairs always returns (i, j) with i < j — flagging
                    # only the LATER index of each match is what keeps the
                    # first pass over a shared stretch a plain single line.
                    mask[idx[:, 1]] = True

            # GPS/track noise between an outbound and return pass means their
            # distance apart isn't constant — it can drift briefly just past
            # LOOP_SHARED_CORRIDOR_PX even in the middle of a genuinely
            # shared stretch, breaking one continuous corridor into several
            # short flagged runs with tiny single-line gaps between them
            # (reported: the red stripe flickering on/off instead of running
            # solid). Closing those small gaps — filling any False run no
            # longer than LOOP_SHARED_GAP_FILL_FRAMES that sits BETWEEN two
            # True runs — keeps a genuinely shared corridor reading as one
            # unbroken stretch without also bridging two unrelated shared
            # stretches that are legitimately far apart.
            max_gap = max(1, int(n * tuning.LOOP_SHARED_GAP_FILL_FRACTION))
            i = 0
            while i < n:
                if not mask[i]:
                    j = i
                    while j < n and not mask[j]:
                        j += 1
                    if i > 0 and j < n and mask[i - 1] and mask[j] and (j - i) <= max_gap:
                        mask[i:j] = True
                    i = j
                else:
                    i += 1

            # A genuinely shared corridor stays close for a SUSTAINED
            # stretch; two different streets that merely cross paths (common
            # in a town's street grid — an intersection, not a shared
            # corridor) only satisfy the raw distance/time checks for a
            # short, isolated run around that one crossing point before
            # diverging again. Clearing any True run shorter than
            # LOOP_SHARED_MIN_RUN_FRACTION removes those incidental-crossing
            # false positives (reported: a return-leg street that only
            # crosses the outbound one, not actually the same road, still
            # showing the dual-stripe look) while leaving a real sustained
            # retrace untouched.
            min_run = max(1, int(n * tuning.LOOP_SHARED_MIN_RUN_FRACTION))
            i = 0
            while i < n:
                if mask[i]:
                    j = i
                    while j < n and mask[j]:
                        j += 1
                    if (j - i) < min_run:
                        mask[i:j] = False
                    i = j
                else:
                    i += 1

        # Some pairs of LEGS (the straight-line stretch of route between
        # two consecutive waypoints) are known to be the exact same
        # physical corridor, not merely geometrically close — job_config
        # can give an explicit "(Return)" duplicate waypoint at the same
        # lat/lng as an earlier waypoint (a ferry dock walked to, then
        # back through on the way home). When two legs' endpoints match
        # each other reversed, that whole leg is shared BY CONSTRUCTION.
        # This matters because a short leg (a straight ferry crossing
        # with no intermediate points) can be nothing but its own two
        # endpoints, leaving the distance/time-based query_pairs check
        # above nothing in the middle to find a match on at all — the
        # general detector can simply never see it. Applied AFTER every
        # heuristic above (not before) so it can't be pruned back out by
        # the min-run/gap-fill passes meant for the fuzzier general case.
        # Only the LATER leg (higher waypoint index) is forced, mirroring
        # the same "first pass stays single line" rule used everywhere
        # else here.
        if points is not None and point_frames is not None and len(points) >= 4:
            match_px = tuning.LOOP_LEG_ENDPOINT_MATCH_PX
            n_points = len(points)
            for i in range(n_points - 1):
                for j in range(i + 2, n_points - 1):
                    if (
                        np.hypot(points[i][0] - points[j + 1][0], points[i][1] - points[j + 1][1])
                        < match_px
                        and np.hypot(points[i + 1][0] - points[j][0], points[i + 1][1] - points[j][1])
                        < match_px
                    ):
                        lo = max(0, min(point_frames[j], point_frames[j + 1]))
                        hi = min(n - 1, max(point_frames[j], point_frames[j + 1]))
                        if hi > lo:
                            mask[lo:hi + 1] = True
        return mask

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
        num_frames = max(10, int(duration * fps))

        start_label, end_label = "開始", "終点"
        for p in [self.out_dir] + list(self.out_dir.parents):
            potential_path = p / "job_config.json"
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

        # Loop route (start_point == end_point, e.g. a ferry crossing
        # walked both out and back) — see GraphicsEngine.draw_path's
        # dual-stripe look for whichever stretch of the line is genuinely
        # walked twice. Reset unconditionally (not just set when true)
        # since self.graphics is one shared instance that renders every
        # project in this process, not a fresh one per render.
        #
        # Rewound to plain single-line for every route (loop or not) —
        # the shared-corridor detection kept surfacing new mismatches
        # against real routed street geometry that no heuristic threshold
        # fully covered. Hard-disabled by never computing/setting the
        # mask (rather than deleting the detection code) so this is a
        # one-line flip to bring back if wanted later.
        _LOOP_LINE_COLORING_ENABLED = False
        point_frames_for_mask = None
        if _LOOP_LINE_COLORING_ENABLED and self._is_loop_route:
            # Each ORIGINAL waypoint's own frame in the animated path —
            # same distance-fraction technique as _estimate_frame further
            # below (duplicated here since that closure isn't built yet
            # at this point), used only to bound which frame RANGE a
            # known-identical leg (see _compute_loop_shared_mask's
            # leg-endpoint pass) covers.
            raw_seg_early = np.hypot(
                np.diff([p[0] for p in points]), np.diff([p[1] for p in points])
            )
            raw_cum_early = np.concatenate([[0.0], np.cumsum(raw_seg_early)])
            raw_total_early = raw_cum_early[-1] if raw_cum_early[-1] > 0 else 1.0
            num_frames_early = len(smooth_path)
            point_frames_for_mask = []
            for pi in range(len(points)):
                frac = raw_cum_early[pi] / raw_total_early
                if cum_smooth_dist is not None:
                    target_dist = frac * total_smooth_dist
                    point_frames_for_mask.append(int(np.searchsorted(cum_smooth_dist, target_dist)))
                else:
                    point_frames_for_mask.append(int(frac * (num_frames_early - 1)))
        self.graphics.loop_shared_mask = (
            self._compute_loop_shared_mask(smooth_path, points, point_frames_for_mask)
            if _LOOP_LINE_COLORING_ENABLED and self._is_loop_route else None
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

        # A stop-by's "x"/"y" above came from points[i] — the nearest
        # point on the RECORDED TRACK, which is fine for a real stop the
        # traveler actually walks to, but wrong for one only observed
        # from a distance (a small offshore island seen from the trail, a
        # viewpoint across the water) — that kind can sit well away from
        # the track, and snapping it onto the nearest track pixel drew
        # its pin right on top of the route line instead of at the real
        # place. Re-projecting from the waypoint's own stored lat/lng (see
        # render_step.py's route_popups) onto this same background image
        # draws it where it actually is. Real (non-stop-by) waypoints keep
        # their track-matched position — they're genuinely visited stops
        # ON the route, so that position is already correct.
        if extent is not None:
            for ap in active_popups:
                if not ap["data"].get("is_stopby"):
                    continue
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
        # Decluttering (fanning overlapping/close pins out into a small
        # circle around their shared center) is deliberately disabled —
        # it moved a waypoint's drawn pin off the actual route line it
        # sits on, reading as "this stop isn't really on the path" even
        # though its real x/y is. Every pin now draws at its true
        # position (_draw_pin already falls back to wp["x"]/wp["y"] when
        # "pin_x"/"pin_y" aren't set — see pins.py), so a tight cluster of
        # stops can visually overlap, but none of them drift off-route.
        # self._declutter_pins(active_popups)

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
        if len(route_obstacle_arr) > 400:
            step = max(1, len(route_obstacle_arr) // 400)
            route_obstacle_arr = route_obstacle_arr[::step]

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
        search_margin = max(20, int(num_frames_lookup * 0.05))
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
        min_leg_frames = int(fps * 1.5)
        for i, ap in enumerate(triggerable):
            this_frame = ap["expected_frame"]
            next_frame = (
                triggerable[i + 1]["expected_frame"]
                if i + 1 < len(triggerable)
                else stop_expected_frame
            )
            if next_frame is not None:
                ap["leg_display_seconds"] = (
                    max(min_leg_frames, next_frame - this_frame) / fps
                )


        intro_freeze_sec = 3.0
        if start_popup and "freeze_seconds" in start_popup["data"]:
            intro_freeze_sec = float(start_popup["data"]["freeze_seconds"])

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
            temp_ep = (
                _make_intro_card(stop_popup)
                if stop_popup and stop_popup["data"].get("popup_image")
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
            self._layout_beside_popups(
                [{"popup": c, "frames_left": 1} for c in intro_cards], w, h,
                card_w=footprint_w, card_h=footprint_h,
                route_obstacles=route_obstacle_arr,
                max_radius=float(max(w, h)),
            )
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
                intro_freeze_sec * 0.5,
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
        # self.graphics is shared with the per-leg residential renderer
        # that runs right after this (see route2vdo.py) — reset so its
        # own, unrelated path_history/draw_path calls never pick up THIS
        # render's loop_shared_mask (indexed against smooth_path, which
        # the per-leg renderer has no equivalent of).
        self.graphics.loop_shared_mask = None
        return video.release(overview_path)
