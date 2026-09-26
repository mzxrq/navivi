"""wait_for_gpu_cooldown: waits while the GPU is hot, until it's cool enough or
the wait limit runs out; never waits when it's cool or unreadable."""

from services import tuning
from services.gpu_cooldown import wait_for_gpu_cooldown


def _readings(*temps):
    it = iter(temps)
    last = [temps[-1]]

    def read():
        try:
            last[0] = next(it)
        except StopIteration:
            pass
        return last[0]

    return read


def test_cool_gpu_does_not_wait():
    slept = []
    assert wait_for_gpu_cooldown(read_temperature=lambda: 50, sleep=slept.append) == 0.0
    assert slept == []


def test_no_reading_does_not_wait():
    assert wait_for_gpu_cooldown(read_temperature=lambda: None, sleep=lambda s: None) == 0.0


def test_hot_gpu_waits_until_it_cools():
    poll = tuning.GPU_COOLDOWN_POLL_SECONDS
    hot, cooling, cool = tuning.GPU_COOLDOWN_START_C + 5, tuning.GPU_COOLDOWN_START_C, tuning.GPU_COOLDOWN_RESUME_C
    waited = wait_for_gpu_cooldown(read_temperature=_readings(hot, cooling, cool), sleep=lambda s: None)
    assert waited == 2 * poll


def test_wait_is_capped():
    waited = wait_for_gpu_cooldown(read_temperature=lambda: 90, sleep=lambda s: None)
    assert waited <= tuning.GPU_COOLDOWN_MAX_WAIT_SECONDS + tuning.GPU_COOLDOWN_POLL_SECONDS
