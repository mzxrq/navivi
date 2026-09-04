"""Fullscreen popup scale-up transition, B-roll playback, and the consolidated
freeze -> scale -> optional B-roll -> hold -> fade sequence."""

import os
from typing import Dict, List, Tuple

import cv2
import numpy as np

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

        # Same geometry render_popup_box itself used to draw the card this
        # is scaling up from (including its beside_box, when the card was
        # placed by _layout_beside_popups) — using a different box here
        # (as this used to, with its own hardcoded size/position guesses)
        # let the growing image start from a visibly different spot than
        # the small card actually sat at.
        box_x, box_y, total_w, total_h, border = self.popup_card_geometry(
            popup_info, w, h
        )
        target_img_w = total_w - border * 2
        target_img_h = int(target_img_w / target_ratio)

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

            # Rack-focus blur: sharp at rest, blurred while mid-scale — the
            # snap from small card to fullscreen reads as a deliberate
            # whip/zoom rather than a plain resize. Blur strength eases out
            # to 0 as the scale-up finishes.
            blur_amount = int(31 * (1.0 - ease))
            if blur_amount > 0:
                k = blur_amount | 1  # cv2.GaussianBlur needs an odd kernel size
                resized_popup = cv2.GaussianBlur(resized_popup, (k, k), 0)

            x0, y0 = max(0, curr_x), max(0, curr_y)
            x1, y1 = min(w, curr_x + curr_w), min(h, curr_y + curr_h)
            px0, py0 = x0 - curr_x, y0 - curr_y
            px1, py1 = px0 + (x1 - x0), py0 + (y1 - y0)

            if x0 < x1 and y0 < y1:
                frame[y0:y1, x0:x1] = resized_popup[py0:py1, px0:px1]
            frames.append(frame)

        full_screen_frame = frames[-1].copy() if frames else hi_res_popup.copy()

        hold_frames_cnt = max(0, int(hold_sec * fps))
        for _ in range(hold_frames_cnt):
            frames.append(full_screen_frame)

        fade_frames = max(0, int(fade_out_sec * fps))
        for t in range(fade_frames):
            progress = t / float(fade_frames - 1) if fade_frames > 1 else 1.0
            alpha = 1.0 - progress
            blended = cv2.addWeighted(
                full_screen_frame, alpha, base_frame, 1 - alpha, 0
            )
            frames.append(blended)

        return frames

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

    def play_fullscreen_popup_sequence(
        self,
        video: VideoExporter,
        base_frame: np.ndarray,
        popup_info: Dict,
        fps: int,
        transition_cfg: Dict[str, float],
        exit_frame: np.ndarray,
    ) -> Tuple[np.ndarray, bool]:
        """Confirm the popup's current position and photo (a brief static
        hold on the small card, confirm_seconds) -> gradually resize it to
        fill the screen (scale_seconds, ~2-3s by default — slow and
        deliberate rather than a snap cut) -> progressive blur, then cut
        (blur_seconds, ~0.5s). A B-roll video (popup_video), when set,
        takes over immediately once the scale finishes instead of the
        blur-and-cut; otherwise the caller's own next beat follows the
        blur."""
        freeze_frame = self.render_popup_box(base_frame, popup_info)
        confirm_t = transition_cfg.get("confirm_seconds", 0.4)
        scale_t = transition_cfg.get("scale_seconds", 2.5)
        blur_t = transition_cfg.get("blur_seconds", 0.5)
        broll_video = popup_info["data"].get("popup_video")

        for _ in range(max(1, int(confirm_t * fps))):
            video.write(freeze_frame)

        t_frames = self.generate_fullscreen_popup_transition(
            base_frame=freeze_frame,
            popup_info=popup_info,
            fps=fps,
            duration_sec=scale_t,
            hold_sec=0.0,
            fade_out_sec=0.0,
        )
        for tf in t_frames:
            video.write(tf)

        if broll_video:
            enter_frame = t_frames[-1] if t_frames else freeze_frame
            self.play_fullscreen_video(broll_video, enter_frame, exit_frame, video, fps)
            return exit_frame, True

        if not t_frames:
            total_freeze = float(popup_info["data"].get("freeze_seconds", 3.0))
            for _ in range(int(total_freeze * fps)):
                video.write(freeze_frame)
            return freeze_frame, False

        full_frame = t_frames[-1]
        blur_frames = max(1, int(blur_t * fps))
        max_ksize = max(3, (min(full_frame.shape[:2]) // 20) | 1)
        blurred = full_frame
        for i in range(blur_frames):
            ksize = max(1, round((i + 1) / blur_frames * max_ksize)) | 1
            blurred = cv2.GaussianBlur(full_frame, (ksize, ksize), 0)
            video.write(blurred)

        return blurred, False
