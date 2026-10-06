"""Auto second shot (2026-10-06): the move is picked from what the photo
shows. Synthetic photos with hand-made depth maps, so no model is loaded."""

import numpy as np

from services import tuning
from services.vdoprocessing import ltx_keyframed, move_picker

MOVES = ("closein", "closeout", "closepanleft", "closepanright", "closepanup", "closepandown",
         "walkthrough", "walkthroughleft", "walkthroughright")
H, W = 216, 384


def _textured(rng):
    return (rng.random((H, W, 3)) * 40 + 100).astype(np.uint8)


def _pick(photo, depth):
    return move_picker.pick(MOVES, move_picker.measure(photo, depth), "s")[0]


def test_a_corridor_walks_in():
    rng = np.random.default_rng(0)
    photo = _textured(rng)
    xs = np.abs(np.linspace(-1, 1, W))[None, :]
    ys = np.linspace(0, 1, H)[:, None]
    depth = np.clip(np.maximum(xs, ys ** 2), 0, 1).astype(np.float32)  # far middle, near walls and floor
    depth[: H // 4] = np.maximum(depth[: H // 4], 0.5)                  # a ceiling, not sky
    assert _pick(photo, depth) == "walkthrough"


def test_a_seascape_pans_toward_the_boat():
    rng = np.random.default_rng(1)
    photo = np.full((H, W, 3), 180, np.uint8)
    photo[H // 2:] = (150, 110, 60)
    photo[H // 2 - 20:H // 2 + 5, W - 110:W - 60] = _textured(rng)[:25, :50] // 3  # the boat
    depth = np.zeros((H, W), np.float32)
    depth[H // 2:] = np.linspace(0.05, 0.6, H - H // 2)[:, None]
    assert _pick(photo, depth) == "closepanright"


def test_a_centred_subject_closes_in():
    rng = np.random.default_rng(2)
    photo = np.full((H, W, 3), 120, np.uint8)
    photo[60:160, 140:240] = _textured(rng)[:100, :100] * 2 % 255
    depth = np.full((H, W), 0.3, np.float32)
    depth[60:160, 140:240] = 0.6
    assert _pick(photo, depth) == "closein"


def test_auto_uses_the_picker_and_falls_back_to_random(monkeypatch):
    from services.vdoprocessing import move_picker as mp

    monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT", "auto")
    monkeypatch.setattr(mp, "pick_for_photo", lambda path, choices, seed: "closepanup")
    assert ltx_keyframed.second_shot("panright", "x", "p.jpg") == "closepanup"
    monkeypatch.setattr(mp, "pick_for_photo", lambda path, choices, seed: None)
    assert ltx_keyframed.second_shot("panright", "x", "p.jpg") in tuning.ATTRACTION_SECOND_SHOT_MOVES


def test_auto_never_repeats_the_first_shots_way(monkeypatch):
    from services.vdoprocessing import move_picker as mp

    seen = {}
    monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT", "auto")
    monkeypatch.setattr(mp, "pick_for_photo", lambda path, choices, seed: seen.setdefault("c", choices)[0])
    ltx_keyframed.second_shot("zoomin", "x", "p.jpg")
    assert "closein" not in seen["c"]
