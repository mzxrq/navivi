"""A stop-by with an attraction clip cuts on the full photo and reopens on the clip's last frame, with no blur."""

import asyncio

from services.vdoprocessing.pydeckrecorder.stopby_pause import _play_stopby_photo_pause


def _run(tmp_path, **extra):
    log = []

    class Page:
        async def evaluate(self, script, arg=None):
            log.append(("js", script, arg))
            return []

        async def screenshot(self, **kwargs):
            return b"frame"

    async def write(_):
        log.append(("frame",))

    async def cut():
        log.append(("cut",))

    (tmp_path / "first.png").write_bytes(b"first")
    (tmp_path / "last.png").write_bytes(b"last")
    html = tmp_path / "html"
    html.mkdir()
    stopby = {"popup_image": str(tmp_path / "first.png"), "lon": 135.0, "lat": 34.0, **extra}
    asyncio.run(_play_stopby_photo_pause(Page(), write, cut, 10, str(html), 0, stopby, 135.0, 34.0, 15.0,
                                         (1920, 1080), 0, 0.0))
    return log, html


def test_reopens_on_the_clips_last_frame(tmp_path):
    log, html = _run(tmp_path, attraction_video="a.mp4", popup_image_after=str(tmp_path / "last.png"))
    assert [e for e in log if e == ("cut",)] == [("cut",)]
    assert not any(e[0] == "js" and "blur(" in e[1] for e in log)
    after = log[log.index(("cut",)) + 1:]
    swap = next(i for i, e in enumerate(after) if e[0] == "js" and "stopby_after_" in str(e[2]))
    assert swap < after.index(("frame",))
    assert [p.read_bytes() for p in html.glob("stopby_after_*")] == [b"last"]


def test_without_a_clip_the_photo_reopens(tmp_path):
    log, html = _run(tmp_path)
    assert [e for e in log if e == ("cut",)] == [("cut",)]
    assert not list(html.glob("stopby_after_*"))
