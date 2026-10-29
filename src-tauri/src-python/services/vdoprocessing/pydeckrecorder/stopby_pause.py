"""A stop-by's photo moment during a walking leg: the small leader-line card, its growth to fullscreen and
the cut into the leg's next piece (or a passing pip card)."""

from __future__ import annotations

import os
import shutil
from typing import List, Optional, Tuple

from services import tuning

from .popupsequence import _wait_for_paint
from .leg_camera import _clear_card_spot, _ease_in_out_cubic, _project_lonlat_to_px

# Screenshot options for every frame a residential leg pipes into ffmpeg
# (read as mjpeg - see _record_leg's _spawn_ffmpeg). All frames of one pipe
# must share this format.
_FRAME_SHOT = {"type": "jpeg", "quality": tuning.LEG_FRAME_JPEG_QUALITY}


async def _play_stopby_photo_pause(
    page, write_frame, cut_to_new_clip, fps, html_dir, port, stopby,
    view_lon, view_lat, zoom, output_size, trigger_index, pitch,
    pip_only: bool = False,
    advance_frame=None, frame_index: int = 0, frame_total: int = 0,
    small_hold_seconds: Optional[float] = None,
    avoid_lonlat: Optional[List[Tuple[float, float]]] = None,
):
    """`avoid_lonlat`: the leg's route; the card goes where it covers the least of it.

    Pauses the walk right where it is, for a connected stop-by (see
    `landmarks` docstring): its own photo pops in as a small leader-line
    card anchored on the marker's own on-screen position (computed from
    the LOCKED camera's known, unmoving viewState -- see
    `_project_lonlat_to_px`), holds, then the ending depends on whether
    this waypoint already has a GENERATED attraction video (the separate
    img2vdo.py/attraction_step.py pipeline stage -- `stopby["attraction_video"]`,
    set by route2vdo.py):

    - No attraction video: the card GROWS to fullscreen, then CUTS the
      leg into a new file (`cut_to_new_clip` closes the current one and
      opens a fresh one, mid-function -- the underlying page/deck.gl
      canvas never stops running, only the ffmpeg sink changes); that new
      file opens on the same fullscreen photo, holds, and shrinks back
      down to nothing right on the marker before the walk resumes.
    - Has an attraction video (`image_display` is ignored - always
      fullscreen): grows to fullscreen like the no-attraction
      case, but ends with a cinematic blur-out (matching popupsequence.
      py's own arrival blur-out) instead of a flat cut, then cuts to a new
      file that likewise resumes the walk directly.

    `pip_only`: for an UNCONNECTED landmark with its own photo -- the
    route only passes NEAR it, so unlike a connected stop-by the walk
    never actually stops there, has no attraction video, and never cuts
    the leg into an extra file. The walker keeps moving along the route
    for the whole pop-in/hold/fade-out beat (via `advance_frame`, the
    caller's own per-frame walker-draw callback) instead of freezing --
    a "look, passing this" aside, not an arrival. Returns the next
    unconsumed frame index so the caller's own loop can resume exactly
    where this left off."""
    photo_path = stopby.get("popup_image")
    if not photo_path or not os.path.exists(photo_path):
        return

    has_attraction = bool(stopby.get("attraction_video"))

    # A per-call UNIQUE filename (not a fixed "stopby_preview.jpg" reused
    # every time this runs) -- a leg with more than one connected stop-by
    # otherwise has every one of them request the exact SAME URL, and the
    # browser's own HTTP cache happily serves back whichever photo it
    # fetched FIRST for every subsequent stop-by, regardless of the file on
    # disk having been overwritten with the next one's actual photo -- the
    # "duplicate image" this trigger index makes impossible.
    img_ext = os.path.splitext(photo_path)[1] or ".jpg"
    img_name = f"stopby_preview_{trigger_index}{img_ext}"
    shutil.copy2(photo_path, os.path.join(html_dir, img_name))
    img_url = f"http://127.0.0.1:{port}/{img_name}"

    freeze_sec = float(stopby.get("freeze_seconds") or tuning.POPUP_MIN_DISPLAY_SECONDS)
    freeze_sec = min(max(freeze_sec, tuning.POPUP_MIN_DISPLAY_SECONDS), tuning.POPUP_FREEZE_SECONDS_MAX)

    out_w, out_h = output_size
    marker_x, marker_y = _project_lonlat_to_px(
        stopby["lon"], stopby["lat"], view_lon, view_lat, zoom, output_size, pitch=pitch
    )
    full_box = (0.0, 0.0, float(out_w), float(out_h))
    # Small leader card, same aspect ratio as the frame itself (keeps the
    # object-fit:cover crop identical at every size -- see the leg-opening
    # sequence's own note on why this matters), floated just above the
    # marker with a leader line connecting its bottom edge down to it. Same
    # size for every card regardless of pip_only -- a pip stays this size
    # the whole time, a connected stop-by's card only starts here before
    # growing to fullscreen, but there's no reason for the two to look
    # like different card sizes in the moment before that growth.
    card_w = 200.0
    card_h = card_w * (float(out_h) / float(out_w))
    card_gap = 26.0
    card_margin = 16.0
    # Clamped to stay fully inside the frame -- a marker near an edge (see
    # the screenshot that prompted this: 石標 sitting right near the top
    # edge) used to float this card straight off-screen, floating it
    # centered/above the marker unconditionally with no bounds check at
    # all. The leader line's own anchor point is recomputed from the
    # CLAMPED box below (its bottom-center), not the marker's raw
    # position, so it still visibly connects to wherever the card actually
    # ended up instead of pointing at empty space.
    card_left = min(
        max(marker_x - card_w / 2.0, card_margin), out_w - card_w - card_margin
    )
    card_top = min(
        max(marker_y - card_gap - card_h, card_margin), out_h - card_h - card_margin
    )
    anchor_x, anchor_y = card_left + card_w / 2.0, card_top + card_h
    if avoid_lonlat:
        card_left, card_top = _clear_card_spot(
            [_project_lonlat_to_px(lo, la, view_lon, view_lat, zoom, output_size, pitch=pitch) for lo, la in avoid_lonlat],
            marker_x, marker_y, card_w, card_h, card_gap, card_margin, out_w, out_h,
        )
        anchor_x = min(max(marker_x, card_left), card_left + card_w)
        anchor_y = min(max(marker_y, card_top), card_top + card_h)
    card_box = (card_left, card_top, card_w, card_h)

    await page.evaluate(
        """([url, left, top, w, h, ax, ay, mx, my]) => new Promise((resolve) => {
            const img = document.createElement('img');
            img.id = 'stopby-preview';
            img.src = url;
            Object.assign(img.style, {
                position: 'fixed', zIndex: '9998',
                left: left + 'px', top: top + 'px', width: w + 'px', height: h + 'px',
                objectFit: 'cover', opacity: '0', borderRadius: '15px',
                boxShadow: '0 15px 35px rgba(0,0,0,0.4)',
            });
            document.body.appendChild(img);

            const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
            svg.id = 'stopby-leader';
            Object.assign(svg.style, {
                position: 'fixed', inset: '0', width: '100vw', height: '100vh',
                zIndex: '9997', pointerEvents: 'none',
            });
            const line = document.createElementNS(svg.namespaceURI, 'line');
            line.id = 'stopby-leader-line';
            line.setAttribute('x1', ax); line.setAttribute('y1', ay);
            line.setAttribute('x2', mx); line.setAttribute('y2', my);
            line.setAttribute('stroke', 'white'); line.setAttribute('stroke-width', '3');
            line.setAttribute('opacity', '0');
            // No dot of its own: the landmark layer already marks the stop-by.
            svg.appendChild(line);
            document.body.appendChild(svg);

            if (img.decode) { img.decode().then(resolve).catch(resolve); }
            else { img.onload = resolve; img.onerror = resolve; }
            setTimeout(resolve, 2000);
        })""",
        [img_url, card_box[0], card_box[1], card_box[2], card_box[3], anchor_x, anchor_y, marker_x, marker_y],
    )
    await _wait_for_paint(page)

    if pip_only:
        # Unconnected landmark: no growth, no attraction video, no leg
        # cut, and (unlike the shared pop-in/hold below) no freeze either
        # -- each rendered step also advances the walker one frame via
        # the caller's own `advance_frame`, so the dot/trail keep moving
        # under the card for the whole pop-in/hold/fade-out beat instead
        # of stalling. Falls back to a plain repeated screenshot (the old
        # frozen behavior) if the caller didn't wire up `advance_frame`.
        idx = frame_index
        pop_frames = max(1, int(0.3 * fps))
        hold_frames = max(1, int(0.5 * fps))
        fade_frames = max(1, int(0.4 * fps))
        for i in range(pop_frames + hold_frames + fade_frames):
            if i < pop_frames:
                alpha = _ease_in_out_cubic((i + 1) / pop_frames)
            elif i < pop_frames + hold_frames:
                alpha = 1.0
            else:
                fade_i = i - (pop_frames + hold_frames)
                alpha = 1.0 - ((fade_i + 1) / fade_frames)
            await page.evaluate(
                """([a]) => {
                    const img = document.getElementById('stopby-preview');
                    if (img) img.style.opacity = a;
                    const line = document.getElementById('stopby-leader-line');
                    if (line) line.setAttribute('opacity', a);
                }""",
                [alpha],
            )
            if advance_frame is not None and idx < frame_total:
                png_bytes = await advance_frame(idx)
                idx += 1
                if png_bytes is None:
                    break
            else:
                await write_frame(await page.screenshot(**_FRAME_SHOT))
        await page.evaluate(
            """() => {
                const svg = document.getElementById('stopby-leader'); if (svg) svg.remove();
                const img = document.getElementById('stopby-preview'); if (img) img.remove();
            }"""
        )
        if not stopby.get("passing"):  # a street photo has no narration piece of its own
            await cut_to_new_clip()
        return idx

    # Pop-in: card + leader line fade/ease in together at their fixed,
    # already-final position (no motion yet -- see the growth phase below
    # for that) -- mirrors the leg-opening sequence's own pop-in beat.
    pop_frames = max(1, int(0.3 * fps))
    for i in range(pop_frames):
        alpha = _ease_in_out_cubic((i + 1) / pop_frames)
        await page.evaluate(
            """([a]) => {
                const img = document.getElementById('stopby-preview');
                if (img) img.style.opacity = a;
                const line = document.getElementById('stopby-leader-line');
                if (line) line.setAttribute('opacity', a);
            }""",
            [alpha],
        )
        await write_frame(await page.screenshot(**_FRAME_SHOT))

    # The small card stays up for `small_hold_seconds` when the walker got here
    # early and is waiting for the narration to finish; only then does it grow.
    hold_png = await page.screenshot(**_FRAME_SHOT)
    for _ in range(max(1, int((0.5 if small_hold_seconds is None else small_hold_seconds) * fps))):
        await write_frame(hold_png)

    # Grow: card -> fullscreen, leader line fading out as it goes (there's
    # nothing left to "point at" once the photo covers the whole frame).
    # This is the LAST beat of the CURRENT clip -- cut_to_new_clip below
    # closes it the instant this loop ends.
    grow_frames = max(1, int(0.6 * fps))
    for i in range(grow_frames):
        t = _ease_in_out_cubic((i + 1) / grow_frames)
        left = card_box[0] + (full_box[0] - card_box[0]) * t
        top = card_box[1] + (full_box[1] - card_box[1]) * t
        w = card_box[2] + (full_box[2] - card_box[2]) * t
        h = card_box[3] + (full_box[3] - card_box[3]) * t
        radius = 15.0 * (1.0 - t)
        await page.evaluate(
            """([left, top, w, h, radius, lineAlpha]) => {
                const img = document.getElementById('stopby-preview');
                if (img) {
                    img.style.left = left + 'px'; img.style.top = top + 'px';
                    img.style.width = w + 'px'; img.style.height = h + 'px';
                    img.style.borderRadius = radius + 'px';
                }
                const line = document.getElementById('stopby-leader-line');
                if (line) line.setAttribute('opacity', lineAlpha);
            }""",
            [left, top, w, h, radius, max(0.0, 1.0 - t * 2.0)],
        )
        await write_frame(await page.screenshot(**_FRAME_SHOT))

    # The leader line/dot have no further use once fullscreen -- gone
    # before the cut so the NEW clip never inherits a stray leftover node.
    await page.evaluate(
        "() => { const svg = document.getElementById('stopby-leader'); if (svg) svg.remove(); }"
    )

    # Hold at fullscreen size BEFORE cutting/blurring -- the grow animation
    # used to run straight into the cut with no pause at all, so the photo
    # was on screen at full size for a single frame before vanishing; a
    # viewer never actually got to register it fullscreen.
    grown_png = await page.screenshot(**_FRAME_SHOT)
    dissolve = has_attraction and bool(stopby.get("dissolve_into_attraction"))
    # With a dissolve (or any cut to an attraction video), the photo is not held:
    # the clip ends as it reaches fullscreen and hands off to the video.
    for _ in range(1 if has_attraction else max(1, int(freeze_sec * fps))):
        await write_frame(grown_png)

    async def reopen_and_shrink(full_hold_sec: float) -> None:
        """The new piece opens on the photo fullscreen and shrinks into its card
        above the marker (as a leg opens on its photo), holds, then fades out."""
        await page.evaluate(
            """([ax, ay, mx, my]) => {
                const img = document.getElementById('stopby-preview');
                if (img) { img.style.filter = ''; img.style.opacity = '1'; }
                const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
                svg.id = 'stopby-leader';
                Object.assign(svg.style, {
                    position: 'fixed', inset: '0', width: '100vw', height: '100vh',
                    zIndex: '9997', pointerEvents: 'none',
                });
                const line = document.createElementNS(svg.namespaceURI, 'line');
                line.id = 'stopby-leader-line';
                line.setAttribute('x1', ax); line.setAttribute('y1', ay);
                line.setAttribute('x2', mx); line.setAttribute('y2', my);
                line.setAttribute('stroke', 'white'); line.setAttribute('stroke-width', '3');
                line.setAttribute('opacity', '0');
                svg.appendChild(line);
                document.body.appendChild(svg);
            }""",
            [anchor_x, anchor_y, marker_x, marker_y],
        )
        full_png = await page.screenshot(**_FRAME_SHOT)
        for _ in range(max(1, int(full_hold_sec * fps))):
            await write_frame(full_png)
        shrink_frames = max(1, int(0.6 * fps))
        for i in range(shrink_frames):
            t = _ease_in_out_cubic((i + 1) / shrink_frames)
            box = [f + (c - f) * t for f, c in zip(full_box, card_box)]
            await page.evaluate(
                """([left, top, w, h, radius, lineAlpha]) => {
                    const img = document.getElementById('stopby-preview');
                    if (img) {
                        img.style.left = left + 'px'; img.style.top = top + 'px';
                        img.style.width = w + 'px'; img.style.height = h + 'px';
                        img.style.borderRadius = radius + 'px';
                    }
                    const line = document.getElementById('stopby-leader-line');
                    if (line) line.setAttribute('opacity', lineAlpha);
                }""",
                [*box, 15.0 * t, max(0.0, t * 2.0 - 1.0)],
            )
            await write_frame(await page.screenshot(**_FRAME_SHOT))
        card_png = await page.screenshot(**_FRAME_SHOT)
        for _ in range(max(1, int(tuning.STOPBY_CARD_HOLD_SECONDS * fps))):
            await write_frame(card_png)
        fade_frames = max(1, int(0.4 * fps))
        for i in range(fade_frames):
            a = 1.0 - (i + 1) / fade_frames
            await page.evaluate(
                """([a]) => {
                    const img = document.getElementById('stopby-preview');
                    if (img) img.style.opacity = a;
                    const line = document.getElementById('stopby-leader-line');
                    if (line) line.setAttribute('opacity', a);
                }""",
                [a],
            )
            await write_frame(await page.screenshot(**_FRAME_SHOT))
        await page.evaluate(
            """() => {
                const svg = document.getElementById('stopby-leader'); if (svg) svg.remove();
                const img = document.getElementById('stopby-preview'); if (img) img.remove();
            }"""
        )

    if has_attraction and dissolve:
        await cut_to_new_clip()
        # Back from the stop-by's attraction video: its photo, then the walk.
        await reopen_and_shrink(tuning.STOPBY_REOPEN_HOLD_SECONDS)
        return

    if has_attraction:
        # Cinematic blur-out (same shape as popupsequence.py's own arrival
        # blur-out: accelerating blur + fade to black) instead of a flat
        # cut -- this is the LAST beat of the CURRENT clip. The new file
        # then resumes the walk directly, same as the pip branch above.
        blur_frames = max(1, int(0.4 * fps))
        for i in range(blur_frames):
            progress = i / float(blur_frames - 1) if blur_frames > 1 else 1.0
            ease = progress ** 2
            blur_px = ease * 40.0
            alpha = 1.0 - progress
            await page.evaluate(
                """([blurPx, alphaVal]) => {
                    const img = document.getElementById('stopby-preview');
                    if (!img) return;
                    img.style.filter = `blur(${blurPx}px)`;
                    img.style.opacity = alphaVal;
                }""",
                [blur_px, alpha],
            )
            await write_frame(await page.screenshot(**_FRAME_SHOT))

        await cut_to_new_clip()
        await reopen_and_shrink(tuning.STOPBY_REOPEN_HOLD_SECONDS)
        return

    # The canvas never stopped rendering across the cut: the walk's map/trail
    # are underneath the photo the whole time.
    await cut_to_new_clip()
    await reopen_and_shrink(freeze_sec)
