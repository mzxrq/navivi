"""The "map" overview (settings.overview_style "map"): the walk overview, with each main stop's photo popping up
big and then sliding over to its leg card (from → to, distance, time, mode, climb). The slide itself is drawn
by GraphicsEngine.render_popup_box (see popup_box.slide_to_card); this gives each stop its card."""

from typing import Dict, List, Optional

import cv2
import numpy as np

from services import tuning

from .base import logger

CARD_SIZE = (768, 432)  # the pop-up's 16:9 photo area


def attach_leg_cards(active_popups: List[Dict], job_config_path: Optional[str], graphics, fps: int) -> None:
    """Stamps "leg_card_bgr" (BGR, CARD_SIZE) on every main stop's data that ends a leg, and a bigger card
    scale; stop-bys that aren't on the route keep the plain small card."""
    from services.localization.route_brief import load_brief
    from services.vdoprocessing.outrocard import _leg_detail_card

    try:
        brief = load_brief(str(job_config_path)) if job_config_path else {}
    except Exception as exc:
        logger.warning("Route map overview: no route facts for the leg cards (%s).", exc)
        brief = {}
    legs_by_to = {leg.get("to_id"): leg for leg in brief.get("legs") or []}
    graphics.slide_fps = fps
    graphics.__dict__.pop("_slide_frames", None)  # a new render: every card starts on its photo again
    route = [
        ap for ap in active_popups
        if (not ap["data"].get("is_stopby") or ap["data"].get("connect_to_route")) and not ap["data"].get("inaccessible")
    ]
    # The overview's own pin numbers (its "order"), so a card never disagrees with its pin.
    badges = [
        "S" if n == 0 else "E" if n == len(route) - 1 else "・" if ap["data"].get("is_stopby") else str(ap.get("order"))
        for n, ap in enumerate(route)
    ]
    marker_rgb = tuple(int(v) for v in reversed(graphics.marker_color[:3]))
    for n, ap in enumerate(route):
        ap["card_scale"] = tuning.OVERVIEW_MAP_CARD_SCALE
        leg = legs_by_to.get(ap["data"].get("id"))
        if not leg or not n:
            continue
        ends = ((badges[n - 1], str(route[n - 1].get("label") or "")), (badges[n], str(ap.get("label") or "")))
        card = _leg_detail_card(graphics, leg, ends, CARD_SIZE, marker_rgb)
        data = ap["data"]
        rgba = np.asarray(card, dtype=np.float32)
        rgb = rgba[..., :3] * (rgba[..., 3:] / 255) + 255 * (1 - rgba[..., 3:] / 255)
        data["leg_card_bgr"] = cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2BGR)
