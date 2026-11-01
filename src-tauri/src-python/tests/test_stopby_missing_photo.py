"""A pip stop-by whose photo file is gone hands the walk back its frame index instead of None (which crashed the leg)."""

import asyncio

from services.vdoprocessing.pydeckrecorder.stopby_pause import _play_stopby_photo_pause


def test_missing_photo_returns_the_frame_index(tmp_path):
    stopby = {"popup_image": str(tmp_path / "gone.jpg"), "lon": 135.0, "lat": 34.0}
    index = asyncio.run(_play_stopby_photo_pause(
        None, None, None, 30, str(tmp_path), 0, stopby, 135.0, 34.0, 15.0, (1920, 1080), 7, 0.0,
        pip_only=True, frame_index=8, frame_total=100,
    ))
    assert index == 8
