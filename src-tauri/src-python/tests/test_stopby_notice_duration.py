from services import tuning
from services.vdoprocessing.spatial_renderer.overview_animation import _OverviewAnimationMixin


def _full_frames(seconds, fps=30):
    r = _OverviewAnimationMixin()
    r._start_stopby_notice(fps, seconds)
    n = r._stopby_notice
    alphas = [min(1.0, (i + 1) / n["fade"], (n["total"] - i) / n["fade"]) for i in range(n["total"])]
    return sum(a >= 1.0 for a in alphas) / fps


def test_short_batch_still_readable():
    assert _full_frames(0.5) >= tuning.STOPBY_NOTICE_MIN_READ_SECONDS


def test_long_hold_kept():
    assert _full_frames(10.0) > 8.0
