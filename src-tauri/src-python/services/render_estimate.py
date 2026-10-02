"""Render-time estimate: workload of a project x this machine's measured speed.

Each pipeline stage has a workload size (characters to voice, video seconds to
render, ...). The cost per unit starts from a rough default scaled by the
detected hardware, and is replaced by the median of the last few real runs
once the pipeline has recorded them (render_timings.json). Cached clips make a
run faster than the estimate, so it is an upper bound after a first render.
"""

import json
import os
import re
import statistics
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

# Same order as pipeline.py's tracker.stage() calls: StageRecorder maps by position.
STAGES = ("gps", "tts", "subtitles", "upscale", "attraction", "route", "intro")
HISTORY_KEEP = 6
HISTORY_MIN_SAMPLES = 2

# Seconds per unit on a mid-range machine (speed factor 1.0).
_DEFAULT_COST = {
    "gps": 2.0,
    "tts": 0.12,
    "subtitles": 0.01,
    "upscale": 6.0,
    "attraction": 90.0,
    "route": 1.6,
    "intro": 8.0,
}
_PAN_ATTRACTION_COST = 6.0
_FIXED_UNITS = ("gps", "intro")


def _small_photos(config: dict) -> int:
    """Waypoint photos the upscale stage would process."""
    from PIL import Image

    from services import tuning
    from services.config.upscaled_images import IMAGE_KEYS, upscale_enabled

    if not upscale_enabled(config.get("settings", {}) or {}):
        return 0
    anchor = Path(config.get("directory_path") or ".")
    seen, count = set(), 0
    for wp in config.get("waypoints", []) or []:
        for key in IMAGE_KEYS:
            value = wp.get(key) if isinstance(wp, dict) else None
            for p in value if isinstance(value, list) else [value]:
                if not isinstance(p, str) or not p or p in seen or p.lower().endswith(".svg"):
                    continue
                seen.add(p)
                path = Path(p) if Path(p).is_absolute() else anchor / p
                try:
                    with Image.open(path) as im:
                        w, h = im.size
                except (OSError, ValueError):
                    continue
                count += w < tuning.IMAGE_UPSCALE_MIN_W or h < tuning.IMAGE_UPSCALE_MIN_H
    return count


def history_path() -> Path:
    return Path.home() / "Documents" / "Navivi" / "render_timings.json"


def _gpu() -> dict:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
        ).stdout.strip().splitlines()
        if out:
            name, mem = [p.strip() for p in out[0].split(",")[:2]]
            return {"name": name, "vram_gb": round(float(mem) / 1024, 1)}
    except Exception:
        pass
    return {"name": None, "vram_gb": 0.0}


def hardware_profile() -> dict:
    cores = os.cpu_count() or 4
    ram = None
    try:
        import psutil

        ram = round(psutil.virtual_memory().total / 2**30, 1)
    except Exception:
        pass
    gpu = _gpu()
    factor = 1.0
    if not gpu["name"]:
        factor *= 1.8
    elif gpu["vram_gb"] < 8:
        factor *= 1.2
    elif gpu["vram_gb"] >= 12:
        factor *= 0.8
    if cores < 8:
        factor *= 1.25
    elif cores >= 16:
        factor *= 0.85
    return {"cpu_cores": cores, "ram_gb": ram, "gpu": gpu["name"], "vram_gb": gpu["vram_gb"], "speed_factor": round(factor, 2)}


def _chars(*texts) -> int:
    total = 0
    for t in texts:
        if isinstance(t, str):
            total += len(re.sub(r"\{[a-z_]+\}", "", t).strip())
    return total


def workload(config: dict) -> dict:
    """Stage -> units of work for a project's job_config."""
    settings = config.get("settings", {}) or {}
    waypoints = config.get("waypoints", []) or []
    fast = bool(settings.get("skip_rich_media", False))
    attractions_on = bool(settings.get("enable_attraction_videos", True)) and not fast

    legs = max(0, len(waypoints) - 1)
    chars = 0 if fast else _chars(
        config.get("overview_narration"),
        *[wp.get("arrivingNarration") or wp.get("narration") for wp in waypoints],
        *[wp.get("attractionNarration") for wp in waypoints],
    )
    clips = sum(1 for wp in waypoints if (wp.get("images") or wp.get("popup_image")) and not wp.get("videos")) if attractions_on else 0
    leg_seconds = float(settings.get("res_duration", 12)) * legs + float(settings.get("duration_seconds", 8))
    return {
        "gps": 1,
        "tts": chars,
        "subtitles": 0 if fast else chars,
        "upscale": _small_photos(config),
        "attraction": clips,
        "route": round(leg_seconds, 1),
        "intro": 1 if config.get("enable_intro", True) else 0,
    }


def load_history() -> dict:
    try:
        return json.loads(history_path().read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cost_per_unit(stage: str, history: dict, speed: float, has_comfy: bool) -> tuple[float, bool]:
    samples = [s for s in history.get(stage, []) if s.get("units")]
    if len(samples) >= HISTORY_MIN_SAMPLES:
        return statistics.median(s["seconds"] / s["units"] for s in samples), True
    base = _DEFAULT_COST[stage]
    if stage == "attraction" and not has_comfy:
        return _PAN_ATTRACTION_COST, False
    return base * speed, False


def estimate(config: dict) -> dict:
    hw = hardware_profile()
    history = load_history()
    units = workload(config)
    has_comfy = (Path(__file__).resolve().parent.parent / "bin" / "ComfyUI").exists()

    stages, measured = {}, 0
    for stage in STAGES:
        n = units[stage]
        if not n:
            stages[stage] = 0.0
            continue
        cost, learned = _cost_per_unit(stage, history, hw["speed_factor"], has_comfy)
        measured += learned
        stages[stage] = round(cost * (1 if stage in _FIXED_UNITS else n), 1)
    active = [s for s in STAGES if units[s]]
    return {
        "success": True,
        "total_seconds": round(sum(stages.values())),
        "stages": stages,
        "units": units,
        "measured_stages": measured,
        "active_stages": len(active),
        "hardware": hw,
    }


class StageRecorder:
    """Times each pipeline stage (hooked on tracker.stage) and stores units/seconds."""

    def __init__(self, config: dict):
        self._units = workload(config)
        self._current: Optional[int] = None
        self._start = 0.0

    def on_stage(self, number: int) -> None:
        self._close()
        self._current, self._start = number, time.monotonic()

    def finish(self) -> None:
        self._close()

    def _close(self) -> None:
        if self._current is None or not 1 <= self._current <= len(STAGES):
            return
        stage = STAGES[self._current - 1]
        units = self._units[stage]
        seconds = time.monotonic() - self._start
        self._current = None
        if units and seconds > 0.5:
            self._store(stage, units, seconds)

    @staticmethod
    def _store(stage: str, units: float, seconds: float) -> None:
        try:
            history = load_history()
            rows = history.setdefault(stage, [])
            rows.append({"units": units, "seconds": round(seconds, 2)})
            history[stage] = rows[-HISTORY_KEEP:]
            path = history_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(history), encoding="utf-8")
        except Exception:
            pass
