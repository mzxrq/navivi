"""Cue timing for the overview animation.

The overview narration's {start} / {n} / {end} cue tags (see localization/cues.py)
are turned into seconds from the real audio (audio_step), and the animation is
retimed here so the traveler is at stop n when the voice reaches {n}. Only the
cues drive it - nothing is sped up to fit the length of the voice.

Pure functions, no rendering: overview.py applies them.
"""

from typing import Dict, List, Optional, Tuple

import numpy as np

# Two stops are never closer than this on screen, whatever the cues say.
MIN_STOP_GAP_FRAMES = 6


def intro_frame_count(intro_freeze_sec: float, clean_hold_sec: float, bounce_frames: int, fps: int) -> int:
    """Frames the intro (clean beat, cards sliding in, hold, sliding out) takes:
    mirrors the writes at the top of render_overview."""
    clean = int(clean_hold_sec * fps)
    remaining = max(0, int(intro_freeze_sec * fps) - clean - bounce_frames)
    return clean + bounce_frames + remaining + bounce_frames


# The walk runs at least this long after the last cued stop: what is left of
# the route (stops nobody talks about, the way back) still has to be travelled.
MIN_SECONDS_AFTER_LAST_CUE = 4.0


# The walk runs at least this long after the last cued stop: what is left of
# the route (stops nobody talks about, the way back) still has to be travelled.
MIN_SECONDS_AFTER_LAST_CUE = 4.0


def animation_frames(cues: Dict[str, float], start_frames: int, fps: int, min_frames: int = 10) -> int:
    """How many frames the walk needs at least so the cued stops fit: it ends
    at the {end} cue, or a little after the last {n} cue. `start_frames` is the
    video's length before the walk starts. 0 when the cues say nothing."""
    end = cues.get("end")
    numbered = [v for k, v in cues.items() if str(k).isdigit()]
    walk_end = 0
    if end is not None:
        walk_end = int(round(end * fps))
    if numbered:
        walk_end = max(walk_end, int(round((max(numbered) + MIN_SECONDS_AFTER_LAST_CUE) * fps)))
    return max(0, walk_end - start_frames) if walk_end else 0


# The walk between two stops is never made more than this many times faster
# than its natural pace to meet a cue: an impossible cue means arriving late,
# not a walker that jumps along the route. Kept low so the walk never looks
# rushed; the script gives each way line enough time instead.
MAX_WALK_SPEEDUP = 1.5


def stop_targets(
    natural: Dict[int, int], cues: Dict[str, float], start_frames: int, fps: int, total: int,
    holds: Optional[Dict[int, int]] = None, cap_frames: Optional[int] = None,
    min_leg_frames: int = 0,
) -> Dict[int, int]:
    """Frame (within the walk) each numbered stop has to be reached at.

    `natural` is the frame each stop is reached at with no retiming, by stop
    number. A stop whose {n} cue exists is pinned to its time; the others keep
    their place relative to their neighbours. Targets are strictly increasing
    and stay inside the walk. `holds`: frames the popups/stop-by batches shown
    before a stop add to the video ahead of it (they are not part of the walk),
    taken off its cue so the stop is reached at the cue in the finished video.
    `min_leg_frames`: no leg is walked faster than this, however short it is
    (a few hundred metres between stops would otherwise flash past, their
    cards piling up at once) - the stop is reached late rather than rushed."""
    order = sorted(natural)
    if not order:
        return {}
    pinned: Dict[int, float] = {}
    for n in order:
        seconds = cues.get(str(n))
        if seconds is not None:
            pinned[n] = seconds * fps - start_frames - (holds or {}).get(n, 0)
    if not pinned:
        return {}
    last = max(1, total - 1)
    targets: Dict[int, float] = {}
    previous_n, previous_target, previous_natural = None, 0.0, 0.0
    for idx, n in enumerate(order):
        if n in pinned:
            targets[n] = pinned[n]
            continue
        # Unpinned: spread between the pinned neighbours by natural spacing.
        left_n = max((m for m in order[:idx] if m in pinned), default=None)
        right_n = min((m for m in order[idx + 1:] if m in pinned), default=None)
        lt, ln = (pinned[left_n], natural[left_n]) if left_n is not None else (0.0, 0.0)
        rt, rn = (pinned[right_n], natural[right_n]) if right_n is not None else (float(last), float(last))
        span = rn - ln
        frac = (natural[n] - ln) / span if span > 0 else 0.5
        targets[n] = lt + frac * (rt - lt)
    # strictly increasing, inside the walk
    out: Dict[int, int] = {}
    floor = 0
    previous_natural = 0
    for n in order:
        slowest_allowed = floor + max(
            MIN_STOP_GAP_FRAMES, min_leg_frames, int((natural[n] - previous_natural) / MAX_WALK_SPEEDUP)
        )
        value = max(targets[n], slowest_allowed)
        if cap_frames:  # a leg never takes longer than the cap - but the cap
            # must never win against the speed floor above: that would rush
            # the walker past MAX_WALK_SPEEDUP just to fit the cap, the exact
            # "rushed" look slowest_allowed exists to prevent. When the two
            # conflict (a short cap on a leg cues demand be walked slowly),
            # the speed floor wins and the stop is reached late instead.
            value = max(slowest_allowed, min(value, floor + cap_frames))
        value = int(round(min(value, last)))
        value = max(value, floor + 1)
        out[n] = value
        floor = value
        previous_natural = natural[n]
    # Squeezed against the end of the walk: pull earlier stops back so every
    # one still fits before the last frame. Kept at least MIN_STOP_GAP_FRAMES
    # apart even while squeezing (not just 1 frame) - this pass runs
    # unconstrained by slowest_allowed above, so without this floor it could
    # cram several stops on top of each other whenever the walk is too short
    # for every cue to fit, instead of spreading the squeeze evenly back.
    ceiling = last
    for n in reversed(order):
        if out[n] > ceiling:
            out[n] = ceiling
        ceiling = max(0, out[n] - MIN_STOP_GAP_FRAMES)
    return out


def warp_controls(
    natural: Dict[int, int], targets: Dict[int, int], total: int, source_total: Optional[int] = None,
) -> Tuple[List[float], List[float]]:
    """(target frames, natural frames) control points, from the walk's start to
    its end through every retimed stop; both strictly increasing. The walk is
    `total` frames long afterwards, out of `source_total` (default: the same)."""
    xs, ys = [0.0], [0.0]
    for n in sorted(targets):
        if targets[n] > xs[-1] and natural[n] > ys[-1]:
            xs.append(float(targets[n]))
            ys.append(float(natural[n]))
    last, source_last = float(total - 1), float((source_total or total) - 1)
    if last > xs[-1] and source_last > ys[-1]:
        xs.append(last)
        ys.append(source_last)
    else:
        xs[-1], ys[-1] = last, source_last
    return xs, ys


def warp_path(
    path: np.ndarray, cum: Optional[np.ndarray], xs: List[float], ys: List[float],
    out_len: Optional[int] = None,
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Resamples the walk so frame xs[i] shows what frame ys[i] showed: the
    traveler speeds up or slows down between stops, the route shape is kept.
    `out_len` frames come out (default: as many as went in)."""
    n = len(path)
    frames = np.arange(n, dtype=float)
    source = np.clip(np.interp(np.arange(out_len or n, dtype=float), xs, ys), 0, n - 1)
    warped = np.stack(
        [np.interp(source, frames, path[:, 0]), np.interp(source, frames, path[:, 1])], axis=1
    )
    warped_cum = np.interp(source, frames, cum) if cum is not None else None
    return warped, warped_cum


def cap_segments(
    path: np.ndarray, cum: Optional[np.ndarray], marks: List[int], cap_frames: int,
) -> Tuple[np.ndarray, Optional[np.ndarray]]:
    """Shortens every leg longer than `cap_frames` (the frames between two
    consecutive waypoint `marks`, which start at frame 0 and end at the last)
    down to the cap by playing it faster; shorter legs are untouched."""
    marks = sorted({int(m) for m in marks})
    xs, ys = [0.0], [0.0]
    for a, b in zip(marks, marks[1:]):
        xs.append(xs[-1] + min(b - a, cap_frames))
        ys.append(float(b))
    if xs[-1] >= ys[-1] or len(xs) < 2:
        return path, cum
    return warp_path(path, cum, xs, ys, out_len=int(round(xs[-1])) + 1)


# --- The ending fits the narration -------------------------------------------
#
# After the walk the overview plays its ending: the recap (every card, held for
# the end popup's freeze_seconds), the summary card fading in and held, the
# highlight on the start point (a lead-in push, a wait, the start photo's hold)
# and a last pause. The narration's closing line plays over it. The summary
# hold and the last pause stretch or shrink so the video ends with the voice;
# they never go below these, so the ending stays readable.
MIN_SUMMARY_HOLD_SECONDS = 1.0
MIN_END_PAUSE_SECONDS = 0.5
# The video may run this far past the voice (or stop this far short of it -
# the mux then holds its last frame) and still count as matching.
AUDIO_MATCH_TOLERANCE_SECONDS = 3.0


def ending_seconds(
    recap_hold: float, summary_fade: float, summary_hold: float,
    highlight_hold: float, pause: float, highlight: bool = True,
) -> float:
    """How long the overview's ending takes, from the end of the walk."""
    from services import tuning

    lead = (tuning.BIG_MAP_ZOOM_LEAD_SECONDS + tuning.ENDING_HIGHLIGHT_WAIT_SECONDS + highlight_hold
            if highlight else 0.0)
    return recap_hold + summary_fade + summary_hold + lead + pause


def fit_ending(remaining_audio: float, fixed: float, summary_hold: float, pause: float) -> Tuple[float, float]:
    """(summary hold, last pause) so the rest of the ending - `fixed` seconds
    that cannot change, plus these two - lasts `remaining_audio` seconds (the
    closing line still to be spoken). Shrinks the summary hold first, then the
    pause, never below their minimums; a longer line stretches the summary hold."""
    spare = remaining_audio - fixed - summary_hold - pause
    if spare >= 0:
        return summary_hold + spare, pause
    hold = max(MIN_SUMMARY_HOLD_SECONDS, summary_hold + spare)
    spare += summary_hold - hold
    return hold, max(MIN_END_PAUSE_SECONDS, pause + spare)
