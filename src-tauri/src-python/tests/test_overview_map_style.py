import numpy as np

from services import tuning
from services.mapfetcher.graphicengine import GraphicsEngine


def test_map_popup_shows_the_photo_then_slides_to_the_leg_card():
    g = GraphicsEngine()
    g.slide_fps = 10
    photo = np.full((90, 160, 3), 50, np.uint8)
    card = np.full((90, 160, 3), 200, np.uint8)
    data = {"leg_card_bgr": card}
    photo_frames = int(tuning.OVERVIEW_MAP_PHOTO_SECONDS * 10)
    shown = [g.slide_to_card(data, photo) for _ in range(photo_frames + int(tuning.OVERVIEW_MAP_SLIDE_SECONDS * 10) + 2)]
    assert (shown[0] == 50).all() and (shown[photo_frames - 1] == 50).all()  # the photo first
    mid = shown[photo_frames + 1]
    assert mid[:, 0].mean() == 50 and mid[:, -1].mean() == 200  # photo leaving left, card coming in from the right
    assert (shown[-1] == 200).all()  # then the card alone


def test_plain_popup_never_slides():
    photo = np.full((9, 16, 3), 50, np.uint8)
    assert GraphicsEngine().slide_to_card({}, photo) is photo


def test_route_map_stop_line_says_the_leg_distance():
    from services.localization.overview_script import leg_facts_line

    assert leg_facts_line({"km": 3.32, "minutes": 86}) == "ここまで3.3キロの道のりでした。"
    assert leg_facts_line({"km": 0.13, "minutes": 3}) == "ここまで130メートルの道のりでした。"
