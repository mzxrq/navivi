"""Waits for the browser to paint the frame just set up (two animation frames)."""


async def _wait_for_paint(page) -> None:
    await page.evaluate(
        "() => new Promise(resolve => "
        "requestAnimationFrame(() => requestAnimationFrame(resolve)))"
    )
