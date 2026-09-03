"""Fullscreen popup scale-up transition, B-roll playback, and the consolidated
freeze -> scale -> optional B-roll -> hold -> fade sequence."""

import os
from typing import Dict, List, Tuple

import cv2
import numpy as np

from services.mapfetcher.mapgeometry import RouteGeometryProcessor
from services.vdoprocessing.vdoexporter import VideoExporter

from .base import logger


class _FullscreenMixin:
    def generate_fullscreen_popup_transition(
        self,
        base_frame: np.ndarray,
        popup_info: Dict,
        fps: int,
        duration_sec: float = 0.8,
        hold_sec: float = 1.5,
        fade_out_sec: float = 0.5,
    ) -> List[np.ndarray]:
        frames = []
        img_url = popup_info["data"].get("popup_image")
        h, w = base_frame.shape[:2]

        if not img_url or not os.path.exists(img_url):
            return frames
        pop_img = self.read_image_safe(img_url)
        if pop_img is None:
            return frames

        ph, pw = pop_img.shape[:2]
        target_ratio = 16.0 / 9.0
        current_ratio = pw / float(ph)

        if current_ratio > target_ratio:
            new_w = int(ph * target_ratio)
            offset = (pw - new_w) // 2
            pop_img = pop_img[:, offset : offset + new_w]
        elif current_ratio < target_ratio:
            new_h = int(pw / target_ratio)
            offset = (ph - new_h) // 2
            pop_img = pop_img[offset : offset + new_h, :]

        hi_res_popup = cv2.resize(pop_img, (w, h))

        target_img_w = 450
        target_img_h = int(target_img_w / target_ratio)
        border = 6
        label_text = popup_info.get("label")

        text_offset = (
            cv2.getTextSize(label_text or "", self.font_cv, 0.6, 1)[0][1] + 15
            if RouteGeometryProcessor.is_real_label(label_text)
            else 0
        )
        total_w, total_h = target_img_w + (border * 2), target_img_h + (border * 2)
        margin = 40
        hud_corner = popup_info.get("hud_corner")
        if hud_corner in self.HUD_CORNERS:
            # Match render_popup_box's placement so the scale-up animation
            # grows from the same spot the preceding pip card sat in,
            # instead of jumping to a position near the map marker.
            box_x, box_y = self._hud_corner_box(hud_corner, w, h, total_w, total_h)
        else:
            box_x = (
                int(popup_info["x"]) - total_w - self.marker_radius - 4
                if popup_info["x"] > w * 0.6
                else int(popup_info["x"]) + self.marker_radius + 4
            )
            box_y = (
                int(popup_info["y"]) + self.marker_radius + 10
                if int(popup_info["y"]) - total_h - text_offset - 10 < margin
                else int(popup_info["y"]) - total_h - text_offset - 10
            )
        box_x = max(margin, min(box_x, w - total_w - margin))
        box_y = max(margin, min(box_y, h - total_h - margin))

        start_x, start_y = box_x + border, box_y + border

        scale_frames = max(1, int(duration_sec * fps))
        for t in range(scale_frames):
            progress = t / float(scale_frames - 1) if scale_frames > 1 else 1.0
            ease = 1 - (1 - progress) ** 3
            curr_w = int(target_img_w + (w - target_img_w) * ease)
            curr_h = int(target_img_h + (h - target_img_h) * ease)
            curr_x = int(start_x + (0 - start_x) * ease)
            curr_y = int(start_y + (0 - start_y) * ease)

            frame = base_frame.copy()
            bg_fade = 1.0 - (0.8 * ease)
            frame = (frame * bg_fade).astype(np.uint8)

            resized_popup = cv2.resize(hi_res_popup, (curr_w, curr_h))
            x0, y0 = max(0, curr_x), max(0, curr_y)
            x1, y1 = min(w, curr_x + curr_w), min(h, curr_y + curr_h)
            px0, py0 = x0 - curr_x, y0 - curr_y
            px1, py1 = px0 + (x1 - x0), py0 + (y1 - y0)

            if x0 < x1 and y0 < y1:
                frame[y0:y1, x0:x1] = resized_popup[py0:py1, px0:px1]
            frames.append(frame)

        hold_frames_cnt = max(1, int(hold_sec * fps))
        full_screen_frame = frames[-1].copy() if frames else hi_res_popup.copy()
        for _ in range(hold_frames_cnt):
            frames.append(full_screen_frame)

        fade_frames = max(1, int(fade_out_sec * fps))
        for t in range(fade_frames):
            progress = t / float(fade_frames - 1) if fade_frames > 1 else 1.0
            alpha = 1.0 - progress
            blended = cv2.addWeighted(
                full_screen_frame, alpha, base_frame, 1 - alpha, 0
            )
            frames.append(blended)

        return frames

    def write_fade_clip(
        self,
        video_out: VideoExporter,
        bg_frame: np.ndarray,
        fg_frame: np.ndarray,
        total_frames: int,
        fade_frames: int,
    ) -> None:
        if fade_frames <= 0:
            for _ in range(total_frames):
                video_out.write(fg_frame)
            return

        for f_idx in range(total_frames):
            if f_idx < fade_frames:
                alpha = f_idx / fade_frames
                blended = cv2.addWeighted(fg_frame, alpha, bg_frame, 1 - alpha, 0)
                video_out.write(blended)
            elif f_idx > total_frames - fade_frames:
                alpha = (total_frames - f_idx) / fade_frames
                blended = cv2.addWeighted(fg_frame, alpha, bg_frame, 1 - alpha, 0)
                video_out.write(blended)
            else:
                video_out.write(fg_frame)

    def play_fullscreen_video(
        self,
        video_path: str,
        enter_frame: np.ndarray,
        exit_frame: np.ndarray,
        video_out: VideoExporter,
        fps: int,
    ) -> None:
        if isinstance(video_path, list):
            video_path = video_path[0] if video_path else ""

        if not video_path or not os.path.exists(video_path):
            logger.warning(f"Video file not found: {video_path}")
            return

        cap = cv2.VideoCapture(video_path)
        frames = []
        target_h, target_w = exit_frame.shape[:2]

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            fh, fw = frame.shape[:2]
            scale = max(target_w / fw, target_h / fh)
            new_w, new_h = int(fw * scale), int(fh * scale)
            resized = cv2.resize(frame, (new_w, new_h))

            y_offset = (new_h - target_h) // 2
            x_offset = (new_w - target_w) // 2
            cropped = resized[
                y_offset : y_offset + target_h, x_offset : x_offset + target_w
            ]
            frames.append(cropped)

        cap.release()

        if not frames:
            return

        fade_frames = min(int(0.5 * fps), len(frames) // 3)
        for i, f in enumerate(frames):
            if i < fade_frames:
                alpha = i / fade_frames
                blended = cv2.addWeighted(f, alpha, enter_frame, 1 - alpha, 0)
                video_out.write(blended)
            elif i > len(frames) - fade_frames:
                alpha = (len(frames) - i) / fade_frames
                blended = cv2.addWeighted(f, alpha, exit_frame, 1 - alpha, 0)
                video_out.write(blended)
            else:
                video_out.write(f)

    def compute_fullscreen_hold_times(
        self, total_freeze: float, transition_cfg: Dict[str, float]
    ) -> Tuple[float, float, float, float]:
        """Calculates the exact frame durations for the 4 phases of a cinematic popup."""
        scale_time = transition_cfg["scale_seconds"]
        fade_time = transition_cfg["fade_out_seconds"]
        hold_full_time = max(
            transition_cfg["min_hold_seconds"],
            total_freeze * transition_cfg["hold_ratio_of_freeze"],
        )
        hold_small_time = max(
            transition_cfg["min_small_hold_seconds"],
            total_freeze - scale_time - hold_full_time - fade_time,
        )
        return hold_small_time, scale_time, hold_full_time, fade_time

    def play_fullscreen_popup_sequence(
        self,
        video: VideoExporter,
        base_frame: np.ndarray,
        popup_info: Dict,
        fps: int,
        transition_cfg: Dict[str, float],
        exit_frame: np.ndarray,
    ) -> Tuple[np.ndarray, bool]:
        """Consolidated logic for freeze -> scale -> optional B-roll -> hold -> fade."""
        freeze_frame = self.render_popup_box(base_frame, popup_info)
        total_freeze = float(popup_info["data"].get("freeze_seconds", 3.0))
        hold_small, scale_t, hold_full, fade_t = self.compute_fullscreen_hold_times(
            total_freeze, transition_cfg
        )

        broll_video = popup_info["data"].get("popup_video")

        if broll_video:
            t_frames = self.generate_fullscreen_popup_transition(
                base_frame=freeze_frame,
                popup_info=popup_info,
                fps=fps,
                duration_sec=scale_t,
                hold_sec=0.1,
                fade_out_sec=0.0,
            )
            if t_frames:
                for _ in range(int(hold_small * fps)):
                    video.write(freeze_frame)
                for tf in t_frames:
                    video.write(tf)
            enter_frame = t_frames[-1] if t_frames else freeze_frame
            self.play_fullscreen_video(broll_video, enter_frame, exit_frame, video, fps)
            return exit_frame, True
        else:
            t_frames = self.generate_fullscreen_popup_transition(
                base_frame=freeze_frame,
                popup_info=popup_info,
                fps=fps,
                duration_sec=scale_t,
                hold_sec=hold_full,
                fade_out_sec=fade_t,
            )
            if t_frames:
                for _ in range(int(hold_small * fps)):
                    video.write(freeze_frame)
                for tf in t_frames:
                    video.write(tf)
            else:
                for _ in range(int(total_freeze * fps)):
                    video.write(freeze_frame)
            return freeze_frame, False
