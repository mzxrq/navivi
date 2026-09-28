"""TileDownloader._crop_to_window: the fetched tile mosaic is cropped to the
padded window that was actually asked for. Tiles are whole-tile chunks, so
without this a padded edge a few metres past a tile edge pulled a whole extra
tile (~5km of sea) onto that side of the overview."""

import numpy as np
import pytest

from services.mapfetcher.maptile import TileDownloader

# 300x200 px mosaic covering x 0..3000 m, y 0..2000 m (10 m/px).
IMG = np.zeros((200, 300, 3), dtype=np.uint8)
EXT = (0.0, 3000.0, 0.0, 2000.0)


class TestCropToWindow:
    def test_crops_to_the_requested_window_on_both_axes(self):
        out, ext = TileDownloader._crop_to_window(IMG, EXT, (1000.0, 2000.0, 500.0, 1500.0))
        assert out.shape[:2] == (100, 100)
        assert ext == pytest.approx((1000.0, 2000.0, 500.0, 1500.0))

    def test_a_window_just_past_a_tile_edge_does_not_pull_in_the_whole_neighbour(self):
        # 47m past x=1000 must cost 47m of extra image, not a whole tile.
        out, ext = TileDownloader._crop_to_window(IMG, EXT, (953.0, 2000.0, 0.0, 2000.0))
        assert ext[0] == pytest.approx(950.0)  # snapped to the pixel grid only
        assert ext[1] == pytest.approx(2000.0)

    def test_row_zero_is_the_north_edge(self):
        marked = IMG.copy()
        marked[0, :, 0] = 255  # top row = north edge (y = 2000)
        out, ext = TileDownloader._crop_to_window(marked, EXT, (0.0, 3000.0, 1000.0, 2000.0))
        assert out[0, 0, 0] == 255 and out.shape[0] == 100
        assert ext[2:] == pytest.approx((1000.0, 2000.0))

    def test_clamped_to_what_the_mosaic_covers(self):
        out, ext = TileDownloader._crop_to_window(IMG, EXT, (-500.0, 4000.0, -500.0, 3000.0))
        assert out.shape == IMG.shape and ext == pytest.approx(EXT)

    def test_a_degenerate_window_leaves_the_mosaic_alone(self):
        out, ext = TileDownloader._crop_to_window(IMG, EXT, (1000.0, 1000.0, 500.0, 500.0))
        assert out.shape == IMG.shape and ext == EXT
