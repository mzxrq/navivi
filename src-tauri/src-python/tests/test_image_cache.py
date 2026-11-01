"""GraphicsEngine.read_image_safe keeps only the last few decoded images (graphicengine/base.py)."""

import cv2
import numpy as np

from services.mapfetcher.graphicengine import GraphicsEngine


def test_the_cache_keeps_the_recent_images_and_hands_out_copies(tmp_path):
    engine = GraphicsEngine()
    paths = []
    for i in range(20):
        path = tmp_path / f"{i}.png"
        cv2.imwrite(str(path), np.full((4, 4, 3), i, dtype=np.uint8))
        paths.append(str(path))
        engine.read_image_safe(str(path))
    engine.read_image_safe(paths[0])  # used again: kept over older ones
    engine.read_image_safe(str(tmp_path / "new.png"))  # missing: nothing cached
    assert len(engine._image_cache) == engine._IMAGE_CACHE_SIZE
    assert paths[19] in engine._image_cache and paths[0] in engine._image_cache and paths[1] not in engine._image_cache
    img = engine.read_image_safe(paths[19])
    img[:] = 255  # a caller drawing on its frame never changes the cached one
    assert int(engine.read_image_safe(paths[19])[0, 0, 0]) == 19
