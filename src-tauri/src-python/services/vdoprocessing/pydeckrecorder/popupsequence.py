"""Shared popup freeze/spin/scale/fade sequence played at waypoint arrivals."""

import math
from typing import Optional


async def _wait_for_paint(page) -> None:
    await page.evaluate(
        "() => new Promise(resolve => "
        "requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )


async def _coin_pop_in(page, force_render_and_shoot, pop_frames: int) -> float:
    """Pops the popup image in like a coin ejected from a block: scales up
    from nothing with a bounce overshoot while spinning around the Y axis,
    landing flat (a multiple of 360deg) so it faces the camera square-on.

    Returns the ending rotation in degrees (0-360) so a following hold can
    continue the spin seamlessly instead of snapping.
    """
    spins = 1.5  # full rotations completed during the pop-in
    end_deg = spins * 360.0

    if pop_frames <= 0:
        await page.evaluate(
            """() => {
                const d = document.getElementById('my-popup-pip');
                if (d) d.style.opacity = 1;
                const img = document.getElementById('my-popup-img-pip');
                if (img) img.style.transform = 'scale(1) rotateY(0deg) translateY(0px)';
            }"""
        )
        return 0.0

    await page.evaluate(
        "() => { document.getElementById('my-popup-pip').style.opacity = 1; }"
    )

    for i in range(pop_frames):
        progress = i / float(pop_frames - 1) if pop_frames > 1 else 1.0
        ease = 1 - (1 - progress) ** 3
        scale = 0.05 + ease * 0.95
        bounce_y = -28.0 * math.sin(progress * math.pi)
        degrees = ease * end_deg
        await page.evaluate(
            """([s, deg, ty]) => {
                const img = document.getElementById('my-popup-img-pip');
                if (img) img.style.transform =
                    `scale(${s}) rotateY(${deg}deg) translateY(${ty}px)`;
            }""",
            [scale, degrees, bounce_y],
        )
        await force_render_and_shoot()

    return end_deg % 360.0


async def _coin_spin_hold(
    page,
    force_render_and_shoot,
    hold_frames: int,
    fps: int,
    start_deg: float,
    deg_per_sec: float = 220.0,
) -> float:
    """Keeps the popup image idly spinning around the Y axis for the
    duration of the hold, like a collectible coin. Returns the ending
    rotation so a following phase can pick up from the same angle."""
    deg = start_deg
    for _ in range(hold_frames):
        deg = (deg + deg_per_sec / fps) % 360.0
        await page.evaluate(
            """([d]) => {
                const img = document.getElementById('my-popup-img-pip');
                if (img) img.style.transform = `scale(1) rotateY(${d}deg) translateY(0px)`;
            }""",
            [deg],
        )
        await force_render_and_shoot()
    return deg


async def _run_popup_freeze_sequence(
    page,
    proc,
    fps: int,
    freeze_frames: int,
    popup_url: Optional[str],
    image_display: str,
    debug_dump_dir: Optional[str] = None,
) -> None:
    if freeze_frames <= 0:
        return

    if not popup_url:
        frozen_png = await page.screenshot()
        for _ in range(freeze_frames):
            proc.stdin.write(frozen_png)
            await proc.stdin.drain()
        return

    safe_display = str(image_display).strip().lower()

    await page.evaluate(
        """([url, displayType]) => {
            return new Promise((resolve) => {
                // 1. PIP Element (Always created first) - doubles as the
                // "coin" stage: pipDiv holds position/frame styling, while
                // pipImg gets the 3D spin/scale/bounce transform.
                const pipDiv = document.createElement('div');
                pipDiv.id = 'my-popup-pip';
                Object.assign(pipDiv.style, {
                    position: 'absolute', zIndex: '9998',
                    top: '50px', right: '50px', width: '500px',
                    backgroundColor: 'white', padding: '15px', borderRadius: '15px',
                    boxShadow: '0 15px 35px rgba(0,0,0,0.4)', opacity: '0',
                    perspective: '1400px'
                });
                const pipImg = document.createElement('img');
                pipImg.id = 'my-popup-img-pip';
                pipImg.src = url;
                Object.assign(pipImg.style, {
                    width: '100%', borderRadius: '10px', display: 'block',
                    transformStyle: 'preserve-3d', backfaceVisibility: 'hidden',
                    transform: 'scale(0.05) rotateY(0deg) translateY(0px)'
                });
                pipDiv.appendChild(pipImg);
                document.body.appendChild(pipDiv);

                // 2. Fullscreen Element (Hidden in the background, only created if needed)
                if (displayType === 'fullscreen') {
                    const fullDiv = document.createElement('div');
                    fullDiv.id = 'my-popup-full';
                    Object.assign(fullDiv.style, {
                        position: 'absolute', zIndex: '9999',
                        top: '0', left: '0', width: '100vw', height: '100vh',
                        backgroundColor: 'rgba(0, 0, 0, 0)',
                        display: 'flex', justifyContent: 'center', alignItems: 'center'
                    });
                    const fullImg = document.createElement('img');
                    fullImg.id = 'my-popup-img-full';
                    fullImg.src = url;
                    Object.assign(fullImg.style, {
                        width: '100vw', height: '100vh', objectFit: 'cover',
                        borderRadius: '0px', boxShadow: 'none',
                        transform: 'scale(0)', transformOrigin: 'center center',
                        willChange: 'transform, opacity'
                    });
                    fullDiv.appendChild(fullImg);
                    document.body.appendChild(fullDiv);
                }

                if (pipImg.decode) {
                    pipImg.decode().then(resolve).catch(resolve);
                } else {
                    pipImg.onload = resolve;
                    pipImg.onerror = resolve;
                }
                setTimeout(resolve, 2000); // hard failsafe
            });
        }""",
        [popup_url, safe_display],
    )

    await _wait_for_paint(page)

    async def force_render_and_shoot() -> None:
        await _wait_for_paint(page)
        png_bytes = await page.screenshot()
        proc.stdin.write(png_bytes)
        await proc.stdin.drain()

    # --- 1. PRE-HOLD MAP FOR 1.5 SECONDS ---
    pre_hold_frames = int(fps * 1.5)
    for _ in range(pre_hold_frames):
        await force_render_and_shoot()

    if safe_display == "fullscreen":
        # --- TIMINGS FOR FULLSCREEN MODE ---
        pip_pop_frames = min(int(fps * 0.5), freeze_frames)
        pip_hold_frames = max(0, freeze_frames - pip_pop_frames)

        full_scale_frames = int(fps * 1.0)
        full_hold_frames = int(fps * 1.5)
        full_fade_frames = int(fps * 0.5)

        # Phase 2: Coin pop-in (scale + Y-axis spin + bounce)
        spin_deg = await _coin_pop_in(page, force_render_and_shoot, pip_pop_frames)

        # Phase 3: Idle coin spin while holding
        await _coin_spin_hold(page, force_render_and_shoot, pip_hold_frames, fps, spin_deg)

        # Phase 4: Scale Fullscreen UP & Fade PIP OUT
        for i in range(full_scale_frames):
            progress = (
                i / float(full_scale_frames - 1) if full_scale_frames > 1 else 1.0
            )
            ease = 1 - (1 - progress) ** 3
            pip_fade = 1.0 - progress
            await page.evaluate(
                """([easeVal, pipFade]) => {
                document.getElementById('my-popup-pip').style.opacity = pipFade;
                document.getElementById('my-popup-img-full').style.transform = `scale(${easeVal})`;
                document.getElementById('my-popup-full').style.backgroundColor = `rgba(0,0,0,${easeVal * 0.85})`;
            }""",
                [ease, pip_fade],
            )
            await force_render_and_shoot()

        # Phase 5: Hold Fullscreen
        for _ in range(full_hold_frames):
            await force_render_and_shoot()

        # Phase 6: Fade Fullscreen Out
        for i in range(full_fade_frames):
            progress = i / float(full_fade_frames - 1) if full_fade_frames > 1 else 1.0
            alpha = 1.0 - progress
            await page.evaluate(
                """([alphaVal]) => {
                document.getElementById('my-popup-img-full').style.opacity = alphaVal;
                document.getElementById('my-popup-full').style.backgroundColor = `rgba(0,0,0,${alphaVal * 0.85})`;
            }""",
                [alpha],
            )
            await force_render_and_shoot()

    else:
        # --- TIMINGS FOR NORMAL PIP MODE ---
        pop_frames = min(int(fps * 0.5), freeze_frames)
        fade_frames = min(int(fps * 0.5), freeze_frames - pop_frames)
        hold_frames = max(0, freeze_frames - pop_frames - fade_frames)

        # Phase 2: Coin pop-in (scale + Y-axis spin + bounce)
        spin_deg = await _coin_pop_in(page, force_render_and_shoot, pop_frames)

        # Phase 3: Idle coin spin while holding
        await _coin_spin_hold(page, force_render_and_shoot, hold_frames, fps, spin_deg)

        # Phase 4: Fade PIP Out
        for i in range(fade_frames):
            progress = i / float(fade_frames - 1) if fade_frames > 1 else 1.0
            alpha = 1.0 - progress
            await page.evaluate(
                "([alphaVal]) => document.getElementById('my-popup-pip').style.opacity = alphaVal;",
                [alpha],
            )
            await force_render_and_shoot()
