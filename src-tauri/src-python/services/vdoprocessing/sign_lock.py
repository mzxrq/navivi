"""Pastes the photo's real signs back over a generated clip.

Video models redraw kanji as kanji-like shapes. The photo's text regions are
found once (RapidOCR detection only), tracked into every frame by SIFT matches
in the surrounding area, and the photo's own pixels are warped over them with
a soft edge and the frame's colours. Frames where a sign can't be tracked keep
the generated pixels.
"""

import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from services import tuning
from services.logger.logger import setup_logger
from services.vdoprocessing.clip_qc import read_image

logger = setup_logger("SignLock")

Rect = Tuple[int, int, int, int]  # x0, y0, x1, y1


def find_signs(photo: np.ndarray) -> List[Rect]:
    """Padded boxes around the photo's text lines."""
    from rapidocr_onnxruntime import RapidOCR

    result, _ = RapidOCR()(photo, use_cls=False, use_rec=False)
    h, w = photo.shape[:2]
    rects = []
    for quad in result or []:
        quad = np.asarray(quad[0] if len(quad) == 3 and np.ndim(quad[0]) == 2 else quad, dtype=np.float32)
        x0, y0 = quad.min(0)
        x1, y1 = quad.max(0)
        if y1 - y0 < tuning.SIGN_LOCK_MIN_TEXT_PX:
            continue
        pad = tuning.SIGN_LOCK_PAD * (y1 - y0)
        rects.append((int(max(0, x0 - pad)), int(max(0, y0 - pad)), int(min(w, x1 + pad)), int(min(h, y1 + pad))))
    return _largest(_merge(rects), tuning.SIGN_LOCK_MAX_SIGNS)


def _merge(rects: List[Rect]) -> List[Rect]:
    """Overlapping padded boxes (lines of one sign) as one box."""
    rects = list(rects)
    merged = True
    while merged:
        merged = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                if a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]:
                    rects[i] = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                    del rects[j]
                    merged = True
                    break
            if merged:
                break
    return rects


def _largest(rects: List[Rect], n: int) -> List[Rect]:
    return sorted(rects, key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), reverse=True)[:n]


def _context(rect: Rect, w: int, h: int) -> Rect:
    x0, y0, x1, y1 = rect
    gx = (x1 - x0) * tuning.SIGN_LOCK_CONTEXT
    gy = (y1 - y0) * tuning.SIGN_LOCK_CONTEXT
    return int(max(0, x0 - gx)), int(max(0, y0 - gy)), int(min(w, x1 + gx)), int(min(h, y1 + gy))


def _corners(rect: Rect) -> np.ndarray:
    x0, y0, x1, y1 = rect
    return np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])


def _plausible(quad: np.ndarray, src: np.ndarray, w: int, h: int) -> bool:
    if not cv2.isContourConvex(quad.reshape(-1, 1, 2).astype(np.float32)):
        return False
    ratio = cv2.contourArea(quad) / max(cv2.contourArea(src), 1.0)
    if not tuning.SIGN_LOCK_MIN_SCALE ** 2 <= ratio <= tuning.SIGN_LOCK_MAX_SCALE ** 2:
        return False
    cx, cy = quad.mean(0)
    return -w * 0.5 < cx < w * 1.5 and -h * 0.5 < cy < h * 1.5


def track(photo: np.ndarray, frames: List[np.ndarray], rect: Rect) -> List[Optional[np.ndarray]]:
    """The sign's 4 corners in each frame (None where it can't be tracked)."""
    sift = cv2.SIFT_create()
    ph, pw = photo.shape[:2]
    cx0, cy0, cx1, cy1 = _context(rect, pw, ph)
    gray = cv2.cvtColor(photo, cv2.COLOR_BGR2GRAY)
    mask = np.zeros_like(gray)
    mask[cy0:cy1, cx0:cx1] = 255
    kp_p, des_p = sift.detectAndCompute(gray, mask)
    src = _corners(rect)
    template = gray[rect[1]:rect[3], rect[0]:rect[2]].astype(np.float32)
    if des_p is None or len(kp_p) < tuning.SIGN_LOCK_MIN_INLIERS:
        return [None] * len(frames)
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    out: List[Optional[np.ndarray]] = []
    prev_gray: Optional[np.ndarray] = None
    for frame in frames:
        fh, fw = frame.shape[:2]
        frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        kp_f, des_f = sift.detectAndCompute(frame_gray, None)
        quad = None
        if des_f is not None and len(kp_f) >= tuning.SIGN_LOCK_MIN_INLIERS:
            good = [m for m, n in (p for p in matcher.knnMatch(des_p, des_f, k=2) if len(p) == 2)
                    if m.distance < 0.75 * n.distance]
            if len(good) >= tuning.SIGN_LOCK_MIN_INLIERS:
                a = np.float32([kp_p[m.queryIdx].pt for m in good])
                b = np.float32([kp_f[m.trainIdx].pt for m in good])
                H, inl = cv2.findHomography(a, b, cv2.RANSAC, 3.0)
                if H is not None and int(inl.sum()) >= tuning.SIGN_LOCK_MIN_INLIERS:
                    q = cv2.perspectiveTransform(src.reshape(-1, 1, 2), H).reshape(4, 2)
                    if _plausible(q, src, fw, fh):
                        quad = q
        if quad is None and out and out[-1] is not None and prev_gray is not None:
            quad = _follow(prev_gray, frame_gray, out[-1], src)
        if quad is not None:
            quad = _snap(template, frame_gray, quad, src)
        out.append(quad)
        prev_gray = frame_gray
    return out


def _snap(template: np.ndarray, gray: np.ndarray, quad: np.ndarray, src: np.ndarray) -> Optional[np.ndarray]:
    """quad refined by ECC alignment of the photo's sign onto the frame; None
    when it doesn't line up (correlation under SIGN_LOCK_MIN_CORR) - a drifted
    track would otherwise paste a ghost sign beside the real board."""
    ph, pw = template.shape[:2]
    H0 = cv2.getPerspectiveTransform(_corners((0, 0, pw, ph)), quad.astype(np.float32))
    seen = cv2.warpPerspective(gray, np.linalg.inv(H0), (pw, ph)).astype(np.float32)
    warp = np.eye(3, dtype=np.float32)
    try:
        cc, warp = cv2.findTransformECC(
            template, seen, warp, cv2.MOTION_HOMOGRAPHY,
            (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 50, 1e-4), None, 5,
        )
    except cv2.error:
        return None
    if cc < tuning.SIGN_LOCK_MIN_CORR:
        return None
    q = cv2.perspectiveTransform(_corners((0, 0, pw, ph)).reshape(-1, 1, 2), H0 @ warp).reshape(4, 2)
    h, w = gray.shape[:2]
    return q if _plausible(q, src, w, h) else None


def _follow(prev_gray: np.ndarray, gray: np.ndarray, quad: np.ndarray, src: np.ndarray) -> Optional[np.ndarray]:
    """quad carried from the previous frame by optical flow around it - once
    the model has redrawn the sign too far for a match against the photo."""
    h, w = gray.shape[:2]
    x0, y0 = np.maximum(quad.min(0) - (quad.max(0) - quad.min(0)) * 0.5, 0).astype(int)
    x1, y1 = np.minimum(quad.max(0) + (quad.max(0) - quad.min(0)) * 0.5, [w, h]).astype(int)
    mask = np.zeros_like(prev_gray)
    mask[y0:y1, x0:x1] = 255
    pts = cv2.goodFeaturesToTrack(prev_gray, 200, 0.01, 4, mask=mask)
    if pts is None or len(pts) < tuning.SIGN_LOCK_FOLLOW_MIN_POINTS:
        return None
    nxt, ok, _ = cv2.calcOpticalFlowPyrLK(prev_gray, gray, pts, None, winSize=(21, 21), maxLevel=3)
    ok = ok.ravel() == 1
    if ok.sum() < tuning.SIGN_LOCK_FOLLOW_MIN_POINTS:
        return None
    H, inl = cv2.findHomography(pts[ok], nxt[ok], cv2.RANSAC, 2.0)
    if H is None or int(inl.sum()) < tuning.SIGN_LOCK_FOLLOW_MIN_POINTS:
        return None
    q = cv2.perspectiveTransform(quad.reshape(-1, 1, 2).astype(np.float32), H).reshape(4, 2)
    return q if _plausible(q, src, w, h) else None


def smooth_track(quads: List[Optional[np.ndarray]]) -> List[Optional[np.ndarray]]:
    """Fills gaps up to SIGN_LOCK_MAX_GAP frames and averages the corners over
    SIGN_LOCK_SMOOTH frames either side, so the pasted sign doesn't jitter."""
    n = len(quads)
    known = [i for i, q in enumerate(quads) if q is not None]
    filled: List[Optional[np.ndarray]] = list(quads)
    for a, b in zip(known, known[1:]):
        if 1 < b - a <= tuning.SIGN_LOCK_MAX_GAP + 1:
            for i in range(a + 1, b):
                t = (i - a) / (b - a)
                filled[i] = quads[a] * (1 - t) + quads[b] * t
    r = tuning.SIGN_LOCK_SMOOTH
    out: List[Optional[np.ndarray]] = []
    for i in range(n):
        if filled[i] is None:
            out.append(None)
            continue
        near = [filled[j] for j in range(max(0, i - r), min(n, i + r + 1)) if filled[j] is not None]
        out.append(np.mean(near, axis=0))
    return out


def fade_weights(quads: List[Optional[np.ndarray]]) -> List[float]:
    """1 inside a tracked run, ramping to 0 over SIGN_LOCK_FADE_FRAMES toward
    an untracked frame (clip ends don't count)."""
    n, f = len(quads), max(1, tuning.SIGN_LOCK_FADE_FRAMES)
    gaps = [i for i, q in enumerate(quads) if q is None]
    out = []
    for i, q in enumerate(quads):
        if q is None:
            out.append(0.0)
            continue
        d = min((abs(i - g) for g in gaps), default=n)
        out.append(min(1.0, d / f))
    return out


def paste(frame: np.ndarray, photo: np.ndarray, rect: Rect, quad: np.ndarray, weight: float = 1.0) -> np.ndarray:
    """The photo's rect warped onto quad in frame, feathered and colour-matched."""
    x0, y0, x1, y1 = rect
    patch = photo[y0:y1, x0:x1].astype(np.float32)
    ph, pw = patch.shape[:2]
    feather = max(1, round(min(pw, ph) * tuning.SIGN_LOCK_FEATHER))
    alpha = np.zeros((ph, pw), np.float32)
    alpha[feather:ph - feather, feather:pw - feather] = 1.0
    alpha = cv2.GaussianBlur(alpha, (0, 0), feather / 2)
    H = cv2.getPerspectiveTransform(_corners((0, 0, pw, ph)), quad.astype(np.float32))
    fh, fw = frame.shape[:2]
    warped = cv2.warpPerspective(patch, H, (fw, fh), flags=cv2.INTER_CUBIC)
    a = cv2.warpPerspective(alpha, H, (fw, fh))[..., None] * weight
    core = a[..., 0] > 0.5 * weight
    if core.sum() < 16:
        return frame
    base = frame.astype(np.float32)
    fit = warped.copy()
    for c in range(3):
        src, dst = warped[..., c][core], base[..., c][core]
        s = dst.std() / max(src.std(), 1.0)
        s = 1.0 + (np.clip(s, 0.7, 1.4) - 1.0) * tuning.SIGN_LOCK_COLOR_STRENGTH
        fit[..., c] = (warped[..., c] - src.mean()) * s + src.mean() + (dst.mean() - src.mean()) * tuning.SIGN_LOCK_COLOR_STRENGTH
    return np.clip(base * (1 - a) + fit * a, 0, 255).astype(np.uint8)


def lock_signs(video_path: str, photo_path: str) -> bool:
    """Rewrites video_path in place with the photo's signs pasted back.
    Returns False (clip untouched) when off, nothing to lock, or on failure."""
    if not tuning.SIGN_LOCK:
        return False
    try:
        photo = read_image(photo_path)
        if photo is None:
            return False
        rects = find_signs(photo)
        if not rects:
            logger.info("No signs found in %s.", Path(photo_path).name)
            return False
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS) or float(tuning.LTXV_FPS)
        frames = []
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frames.append(frame)
        cap.release()
        if not frames:
            return False

        tracks = [(rect, smooth_track(track(photo, frames, rect))) for rect in rects]
        tracks = [(rect, quads, fade_weights(quads)) for rect, quads in tracks]
        for rect, quads, _ in tracks:
            logger.info("Sign %s tracked in %d of %d frames of %s.", rect,
                        sum(q is not None for q in quads), len(frames), Path(video_path).name)
        if not any(q is not None for _, quads, _ in tracks for q in quads):
            return False

        from services.tts.ttsengine import FFmpegManager

        h, w = frames[0].shape[:2]
        out_path = str(Path(video_path).with_suffix(".signlock.mp4"))
        proc = subprocess.Popen(
            [
                FFmpegManager.resolve_ffmpeg_bin(), "-y", *tuning.ffmpeg_pipe_log_args(),
                "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps:.3f}", "-i", "-",
                "-c:v", "libx264", *tuning.ffmpeg_thread_args(), "-crf", "16", "-preset", "fast",
                "-pix_fmt", "yuv420p", out_path,
            ],
            stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            for i, frame in enumerate(frames):
                for rect, quads, weights in tracks:
                    if quads[i] is not None and weights[i] > 0:
                        frame = paste(frame, photo, rect, quads[i], weights[i])
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            if proc.wait() != 0:
                logger.warning("Sign lock encode failed: %s", proc.stderr.read().decode("utf-8", "replace"))
                Path(out_path).unlink(missing_ok=True)
                return False
        except Exception:
            proc.kill()
            Path(out_path).unlink(missing_ok=True)
            raise
        Path(out_path).replace(video_path)
        return True
    except Exception as exc:
        logger.warning("Sign lock failed for %s (%s) - keeping the generated signs.", video_path, exc)
        return False
