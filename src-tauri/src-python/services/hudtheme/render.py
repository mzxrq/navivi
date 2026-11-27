"""Themed cards -> transparent pictures, in headless Chromium on the CPU (never the GPU: this machine crashes)."""

from __future__ import annotations

import io
from pathlib import Path
from typing import List, Sequence

from PIL import Image

from services.hudtheme import styles
from services.hudtheme.cards import Card

PAD = 24  # artboard px of empty margin around each picture, for the card's shadow
_VIEWPORT = {"width": 1100, "height": 600}  # room for the biggest card
_FONT_DIR = Path(__file__).parents[2] / "assets" / "fonts"
_HOST = "https://hud.local/"
_FONTS = (
    ("Zen Maru Gothic", 700, "ZenMaruGothic-Bold.ttf"),
    ("Zen Maru Gothic", 900, "ZenMaruGothic-Black.ttf"),
    ("LINE Seed JP", 700, "LINESeedJP-Bold.ttf"),  # for the rare kanji the two above lack
)
_FIT_JS = """async () => {
    await Promise.all([...document.fonts].map(f => f.load()));
    for (const el of document.querySelectorAll('.fit')) {
        let size = parseFloat(getComputedStyle(el).fontSize);
        const min = size * 0.55;
        while (el.scrollWidth > el.clientWidth && size > min) { size -= 0.5; el.style.fontSize = size + 'px'; }
    }
    const same = [...document.querySelectorAll('.same')];  // all as small as the one shrunk most
    const least = Math.min(...same.map(el => parseFloat(getComputedStyle(el).fontSize)));
    for (const el of same) el.style.fontSize = least + 'px';
    for (const el of document.querySelectorAll('.flow div')) {  // the card grows, but a name stops at two lines
        let size = parseFloat(getComputedStyle(el).fontSize);
        const min = size * 0.7, two = 2 * parseFloat(getComputedStyle(el).lineHeight) + 1;
        while (el.offsetHeight > two && size > min) { size -= 0.5; el.style.fontSize = size + 'px'; }
    }
    for (const el of document.querySelectorAll('.wrap')) {
        // Chromium breaks at <wbr> even under nowrap, so a long Japanese name shows as height, not width.
        if (el.scrollWidth <= el.clientWidth && el.scrollHeight < el.clientHeight * 1.5) continue;
        const [top, height, full] = el.dataset.two.split(' ').map(Number);
        Object.assign(el.style, { top: top + 'px', height: height + 'px', lineHeight: height / 2 + 'px',
                                  fontSize: full + 'px', whiteSpace: 'normal' });
        // A word wider than the box, or a third line.
        const over = () => el.scrollWidth > el.clientWidth || el.scrollHeight >= height * 1.25;
        let size = full;
        while (over() && size > full * 0.75) { size -= 0.5; el.style.fontSize = size + 'px'; }
        if (over()) {
            Object.assign(el.style, { overflowWrap: 'anywhere', display: '-webkit-box', webkitBoxOrient: 'vertical',
                                      webkitLineClamp: '2' });
        }
    }
}"""


def _page_html() -> str:
    faces = "".join(
        f"@font-face {{ font-family: '{family}'; font-weight: {weight}; src: url('{_HOST}{name}'); }}"
        for family, weight, name in _FONTS)
    css = (styles.BUILTIN_DIR / "base.css").read_text(encoding="utf-8")
    return (f"<!doctype html><meta charset='utf-8'><style>{faces}{css}"
            f"html,body{{margin:0;background:transparent}} body{{padding:{PAD}px}}</style><body></body>")


def _serve_font(route) -> None:
    name = route.request.url[len(_HOST):]
    if name not in (found for _, _, found in _FONTS):
        route.abort()
        return
    route.fulfill(path=str(_FONT_DIR / name), content_type="font/ttf",
                  headers={"Access-Control-Allow-Origin": "*"})


def _new_page(browser, scale: float):
    """A page that can load the bundled fonts and nothing else, and runs no script of its own: a style file may
    be someone else's. (page.evaluate still works.)"""
    page = browser.new_page(device_scale_factor=scale, viewport=_VIEWPORT, java_script_enabled=False)
    page.route("**/*", lambda route: route.abort())
    page.route(_HOST + "*", _serve_font)  # the later route wins
    page.set_content(_page_html())
    return page


def render_cards(cards: Sequence[Card], scale: float) -> List[Image.Image]:
    """RGBA pictures of `cards`, `scale` video px per artboard px. Each is PAD wider on every side than its
    card (a `.grow` card may be bigger than the Card says), so it goes at (card position - PAD) * scale."""
    from playwright.sync_api import sync_playwright

    if not cards:
        return []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-gpu"])
        try:
            page = _new_page(browser, scale)
            out = []
            for card in cards:
                page.evaluate("html => { document.body.innerHTML = html; }", card.html)
                page.evaluate(_FIT_JS)
                box = page.locator(".card").bounding_box()
                shot = page.screenshot(omit_background=True, clip={
                    "x": 0, "y": 0, "width": box["width"] + 2 * PAD, "height": box["height"] + 2 * PAD})
                out.append(Image.open(io.BytesIO(shot)).convert("RGBA"))
            return out
        finally:
            browser.close()
