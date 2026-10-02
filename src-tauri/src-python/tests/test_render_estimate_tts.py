"""The first narration estimate on a CPU PC: close to what a real run costs, instead of ~10x too low."""

import pytest

from services import render_estimate as re_
from services import tuning

CPU = {"gpu": None}
GPU = {"gpu": "NVIDIA RTX"}


def seconds(requests, chars, quality="best", saved=True):
    return re_.cpu_narration_seconds(requests, chars, int(tuning.TTS_QUALITY_PRESETS[quality]["num_steps"]), saved)


def test_matches_the_measured_requests_to_within_a_fifth():
    measured = {  # (characters, preset) -> seconds, one request each, saved latent
        (6, "best"): 40.0, (14, "best"): 45.3, (31, "best"): 77.0,
        (6, "balanced"): 26.2, (14, "balanced"): 30.7, (31, "balanced"): 50.9,
        (6, "fast"): 19.5, (14, "fast"): 24.8, (31, "fast"): 42.0,
    }
    for (chars, preset), took in measured.items():
        assert seconds(1, chars, preset) == pytest.approx(took, rel=0.2)


def test_fewer_steps_and_a_saved_latent_are_cheaper():
    assert seconds(5, 100, "fast") < seconds(5, 100, "balanced") < seconds(5, 100, "best")
    assert seconds(5, 100, saved=True) < seconds(5, 100, saved=False)


def test_many_short_lines_cost_more_than_the_same_text_in_one_request():
    assert seconds(10, 100) > seconds(1, 100)


def test_nothing_to_say_costs_nothing():
    assert seconds(0, 0) == 0


def test_requests_follow_how_the_text_is_chunked():
    assert re_._tts_requests([]) == 0
    assert re_._tts_requests(["", None, "  "]) == 0
    assert re_._tts_requests(["お疲れ様です"]) == 1
    assert re_._tts_requests(["お疲れ様です", "ユニバーサルシティへようこそ"]) == 2
    assert re_._tts_requests(["{cue} " + "あ" * 200]) > 1


def test_the_cpu_estimate_applies_without_a_gpu_only():
    units = {"tts": 100, "tts_requests": 5}
    assert re_._narration_estimate({"settings": {}}, units, GPU) is None
    cpu = re_._narration_estimate({"settings": {"tts": {"quality": "fast"}}}, units, CPU)
    best = re_._narration_estimate({"settings": {"tts": {"quality": "best"}}}, units, CPU)
    assert cpu is not None and best is not None and cpu < best
    assert best > 100  # for 100 characters / 5 lines this is minutes, not the old ~20 s


def test_estimate_uses_it_for_a_project_with_narration(monkeypatch):
    monkeypatch.setattr(re_, "hardware_profile", lambda: {"cpu_cores": 12, "ram_gb": 15.3, "gpu": None, "vram_gb": 0.0, "speed_factor": 2.25})
    monkeypatch.setattr(re_, "load_history", lambda: {})
    config = {"settings": {}, "waypoints": [{"arrivingNarration": "お疲れ様です"}, {"arrivingNarration": "ユニバーサルシティへようこそ"}]}
    result = re_.estimate(config)
    assert result["units"]["tts_requests"] == 2
    assert result["stages"]["tts"] > 60


def test_the_fast_voice_is_estimated_in_seconds_not_minutes():
    # 3 waypoints of narration on the Kokoro engine: ~12 lines, ~300 characters
    kokoro = re_.kokoro_narration_seconds(12, 300)
    assert 40 < kokoro < 120
    assert kokoro < re_.cpu_narration_seconds(12, 300, 40, True) / 5
    assert re_.kokoro_narration_seconds(0, 0) == 0


def test_the_engine_in_the_project_decides_which_estimate_is_used():
    units = {"tts": 300, "tts_requests": 12}
    on_gpu = {"gpu": "NVIDIA RTX"}
    kokoro = {"settings": {"tts": {"engine": "kokoro"}}}
    assert re_._narration_estimate(kokoro, units, on_gpu) == pytest.approx(re_.kokoro_narration_seconds(12, 300))
    assert re_._narration_estimate({"settings": {}}, units, on_gpu) is None  # Irodori on a GPU: the generic cost
    assert re_._narration_estimate({"settings": {}}, units, CPU) > 300  # Irodori on a CPU


def test_the_balanced_voice_sits_between_the_other_two():
    fast = re_.kokoro_narration_seconds(12, 300)
    balanced = re_.qwen3_narration_seconds(12, 300)
    natural = re_.cpu_narration_seconds(12, 300, 40, True)
    assert fast < balanced < natural
    assert re_.qwen3_narration_seconds(0, 0) == 0


def test_the_balanced_estimate_matches_what_was_measured():
    # 6, 14 and 31 characters took 10, 13 and 31 s once the model was loaded
    for chars, took in ((6, 10.4), (14, 13.0), (31, 31.4)):
        assert re_.qwen3_narration_seconds(1, chars) - 40 == pytest.approx(took, rel=0.3)
    # the 64-character, three-line narration took about 65 s at 1.25x speed (~9.5 s of audio)
    assert re_.qwen3_narration_seconds(3, 64) - 40 == pytest.approx(69, rel=0.2)


def test_the_estimate_follows_the_projects_engine():
    units = {"tts": 300, "tts_requests": 12}
    qwen = {"settings": {"tts": {"engine": "qwen3"}}}
    assert re_._narration_estimate(qwen, units, {"gpu": "NVIDIA RTX"}) == pytest.approx(re_.qwen3_narration_seconds(12, 300))
