"""Cut/fade and blur-out transition primitives, plus the end-of-video recap,
summary card, and higher-zoom "callback to where the journey began" highlight."""

from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter


class _TransitionMixin:
    @staticmethod
    def _cut_fade_transition(
        video: VideoExporter,
        from_frame: np.ndarray,
        to_frame: np.ndarray,
        fps: int,
        duration_sec: float = 0.8,
    ) -> None:
        """Jump cut then fade: writes `from_frame` once more (the cut),
        then a plain crossfade dissolve into `to_frame` — no push/zoom
        motion, since `to_frame` is a different, non-geo-aligned image
        (a freshly fetched higher-zoom map) that a zoom/pan would not
        actually be zooming "into"."""
        video.write(from_frame)
        n = max(1, int(duration_sec * fps))
        for i in range(n):
            alpha = (i + 1) / n
            video.write(cv2.addWeighted(to_frame, alpha, from_frame, 1 - alpha, 0))

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
    _ENDING_HIGHLIGHT_WAIT_SECONDS = 1.5

    def _render_ending_highlight(
        self,
        video: VideoExporter,
        w: int,
        h: int,
        fps: int,
        stop_popup: Dict,
        start_popup: Optional[Dict] = None,
    ) -> bool:
        """End-of-video highlight: cut+fade from the recap into a freshly
        fetched, genuinely higher-zoom map centered on the trip's START
        point — with its own marker and a leader-lined popup, featuring
        the start waypoint's own photo — then, after a short hold, hand
        off to a fullscreen photo transition (if that waypoint's
        image_display is "fullscreen") or just hold on the pip card. A
        "callback to where the journey began" reveal to close the video,
        rather than repeating the end waypoint's own photo (already shown
        in the recap). Falls back to the end waypoint/point if there's no
        start one available.

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
        self.graphics.draw_marker(
            highlight_bg, px, py,
            number="S" if is_start else "E",
            color=self._START_PIN_COLOR if is_start else self._END_PIN_COLOR,
        )

        featured_popup = start_popup or stop_popup
        highlight_popup = featured_popup.copy()
        highlight_popup["data"] = featured_popup["data"].copy()
        highlight_popup["x"], highlight_popup["y"] = px, py
        highlight_popup["hud_corner"] = None  # forces the leader-lined "beside" card style
        highlight_popup["draw_leader_line"] = True
        # Same short-leader-line placement flow-through popups use
        # elsewhere (starts ~55px from the pin, spiraling out only if that
        # spot's taken) — without this, render_popup_box's own fallback
        # placement (meant for corner-avoidance, not a tight leader line)
        # can land the card far across the frame.
        self._layout_beside_popups([{"popup": highlight_popup, "frames_left": 1}], w, h)
        highlight_frame = self.graphics.render_popup_box(highlight_bg, highlight_popup)

        self._cut_fade_transition(video, self.last_frame, highlight_frame, fps)
        for _ in range(int(self._ENDING_HIGHLIGHT_WAIT_SECONDS * fps)):
            video.write(highlight_frame)
        self.last_frame = highlight_frame

        if (
            self.enable_fullscreen_popups
            and highlight_popup["data"].get("image_display") == "fullscreen"
        ):
            scale_sec = self.transition_cfg["scale_seconds"]
            hold_sec = self.transition_cfg["min_hold_seconds"]
            t_frames = self.graphics.generate_fullscreen_popup_transition(
                base_frame=highlight_frame,
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
        else:
            highlight_hold_sec = float(highlight_popup["data"].get("freeze_seconds", 3.0))
            for _ in range(int(highlight_hold_sec * fps)):
                video.write(highlight_frame)
        return False
