"""Finds where a generated attraction shot stops being its photo.

Each frame is matched to the photo (SIFT + RANSAC homography: the camera
move), then cut into patches; a patch the photo doesn't have near the spot the
camera model maps it to is content Wan made up - an invented sign, a hand, a
person. Parallax only shifts patches a little, so real camera motion passes.
"""

from typing import List, Optional, Tuple

import cv2
import numpy as np

from services import tuning
from services.logger.logger import setup_logger
from services.vdoprocessing.color_match import _crop_to_aspect

logger = setup_logger("ClipQC")

_WIDTH = 640
_PATCH = 32
_SEARCH = 32
_MIN_MATCHES = 12
_MIN_NCC = 0.45
_MAX_COLOR_DIFF = 22.0
_MIN_TEXTURE_STD = 12.0
# Moves whose new view necessarily shows what's beyond the photo.
REVEALING_MOVES = {"panright", "panleft", "panup", "pandown", "zoomout", "dollyback"}


def _small(image: np.ndarray) -> np.ndarray:
    h, w = image.shape[:2]
    return cv2.resize(image, (_WIDTH, max(1, round(h * _WIDTH / w))), interpolation=cv2.INTER_AREA)


def read_image(path: str) -> Optional[np.ndarray]:
    """cv2.imread that also opens a non-ASCII Windows path."""
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        image = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_COLOR)
    return image


def read_frames(video_path: str) -> List[np.ndarray]:
    cap = cv2.VideoCapture(video_path)
    frames = []
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
    finally:
        cap.release()
    return frames


class _Reference:
    def __init__(self, photo: np.ndarray, width: int, height: int):
        self.image = _small(_crop_to_aspect(photo, width, height))
        self.gray = cv2.cvtColor(self.image, cv2.COLOR_BGR2GRAY)
        self.lab = cv2.cvtColor(self.image, cv2.COLOR_BGR2LAB).astype(np.float32)
        self.sift = cv2.SIFT_create(2000)
        self.keypoints, self.descriptors = self.sift.detectAndCompute(self.gray, None)
        self.matcher = cv2.BFMatcher()


def frame_problems(frame: np.ndarray, ref: _Reference) -> Tuple[float, int, float]:
    """(share of patches not found in the photo, size of the biggest
    connected group of them, share of patches mapping outside the photo)."""
    small = _small(frame)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)
    keypoints, descriptors = ref.sift.detectAndCompute(gray, None)
    if descriptors is None or ref.descriptors is None or len(keypoints) < 2:
        return 1.0, 10**6, 1.0
    good = [
        m for m, n in (p for p in ref.matcher.knnMatch(descriptors, ref.descriptors, k=2) if len(p) == 2)
        if m.distance < 0.75 * n.distance
    ]
    if len(good) < _MIN_MATCHES:
        return 1.0, 10**6, 1.0
    to_photo, _ = cv2.findHomography(
        np.float32([keypoints[m.queryIdx].pt for m in good]),
        np.float32([ref.keypoints[m.trainIdx].pt for m in good]),
        cv2.RANSAC, 4.0,
    )
    if to_photo is None:
        return 1.0, 10**6, 1.0

    h, w = gray.shape
    rh, rw = ref.gray.shape
    rows, cols = h // _PATCH, w // _PATCH
    bad = np.zeros((rows, cols), np.uint8)
    outside = np.zeros_like(bad)
    centres = np.float32([[[(c + 0.5) * _PATCH, (r + 0.5) * _PATCH]] for r in range(rows) for c in range(cols)])
    mapped = cv2.perspectiveTransform(centres, to_photo).reshape(rows, cols, 2)
    half = _PATCH / 2
    for r in range(rows):
        for c in range(cols):
            mx, my = mapped[r, c]
            px, py = int(round(mx - half)), int(round(my - half))
            if px < -half or py < -half or px > rw - half or py > rh - half:
                outside[r, c] = 1
                continue
            x0, y0 = max(0, px - _SEARCH), max(0, py - _SEARCH)
            x1, y1 = min(rw, px + _PATCH + _SEARCH), min(rh, py + _PATCH + _SEARCH)
            if x1 - x0 < _PATCH or y1 - y0 < _PATCH:
                outside[r, c] = 1
                continue
            y, x = r * _PATCH, c * _PATCH
            patch = gray[y:y + _PATCH, x:x + _PATCH]
            res = cv2.matchTemplate(ref.gray[y0:y1, x0:x1], patch, cv2.TM_CCOEFF_NORMED)
            _, ncc, _, loc = cv2.minMaxLoc(res)
            bx, by = x0 + loc[0], y0 + loc[1]
            color_diff = np.abs(
                lab[y:y + _PATCH, x:x + _PATCH].mean((0, 1)) - ref.lab[by:by + _PATCH, bx:bx + _PATCH].mean((0, 1))
            ).max()
            if (patch.std() > _MIN_TEXTURE_STD and ncc < _MIN_NCC) or color_diff > _MAX_COLOR_DIFF:
                bad[r, c] = 1
    count, _, stats, _ = cv2.connectedComponentsWithStats(bad, connectivity=4)
    cluster = int(stats[1:, cv2.CC_STAT_AREA].max()) if count > 1 else 0
    return float(bad.mean()), cluster, float(outside.mean())


def is_bad(problems: Tuple[float, int, float], reveals: bool) -> bool:
    bad_share, cluster, outside = problems
    outside_cap = tuning.ATTRACTION_QC_MAX_OUTSIDE_REVEAL if reveals else tuning.ATTRACTION_QC_MAX_OUTSIDE
    return (
        bad_share > tuning.ATTRACTION_QC_MAX_BAD_FRACTION
        or cluster >= tuning.ATTRACTION_QC_MAX_BAD_CLUSTER
        or outside > outside_cap
    )


def first_bad_frame(
    frames: List[np.ndarray], photo: np.ndarray, reveals: bool = False,
) -> Optional[int]:
    """Index of the first frame that is no longer the photo, None if all are."""
    if not frames:
        return 0
    h, w = frames[0].shape[:2]
    ref = _Reference(photo, w, h)
    for i, frame in enumerate(frames):
        problems = frame_problems(frame, ref)
        if is_bad(problems, reveals):
            logger.info(
                "QC: frame %d/%d goes bad (%.0f%% unknown, cluster %d, %.0f%% outside the photo).",
                i, len(frames), problems[0] * 100, problems[1], problems[2] * 100,
            )
            return i
    return None


def scene_lost_frame(frames: List[np.ndarray], photo: np.ndarray, step: int = 3) -> Optional[int]:
    """First frame (checked every `step`) sharing too few features with the photo
    to still be the same place, None if all do. Epipolar inliers, not a
    homography: a real walk changes perspective. Calibrated 2026-10-07: test23's
    station walk kept >= 15 of 254; the invented forest corridor fell to 8 of
    647 at 1.0 s and 0 after."""
    if not frames:
        return None
    h, w = frames[0].shape[:2]
    ref = _Reference(photo, w, h)
    if ref.descriptors is None:
        return None
    floor = None
    for i in range(0, len(frames), step):
        gray = cv2.cvtColor(_small(frames[i]), cv2.COLOR_BGR2GRAY)
        keypoints, descriptors = ref.sift.detectAndCompute(gray, None)
        inliers = 0
        if descriptors is not None and len(keypoints) >= 8:
            good = [
                m for m, n in (p for p in ref.matcher.knnMatch(descriptors, ref.descriptors, k=2) if len(p) == 2)
                if m.distance < 0.75 * n.distance
            ]
            if len(good) >= 8:
                _, mask = cv2.findFundamentalMat(
                    np.float32([keypoints[m.queryIdx].pt for m in good]),
                    np.float32([ref.keypoints[m.trainIdx].pt for m in good]), cv2.FM_RANSAC, 3.0,
                )
                inliers = int(mask.sum()) if mask is not None else 0
        if floor is None:
            floor = max(tuning.LTXV_WALK_QC_MIN_INLIERS, tuning.LTXV_WALK_QC_MIN_SHARE * inliers)
        elif inliers < floor:
            logger.info("QC: frame %d/%d left the photo (%d inliers, need %.0f).", i, len(frames), inliers, floor)
            return i
    return None
