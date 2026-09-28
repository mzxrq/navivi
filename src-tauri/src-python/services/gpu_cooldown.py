"""A short cooldown between GPU-heavy jobs: wait for a hot GPU to cool down
before starting the next one (tuning.GPU_COOLDOWN_*)."""

import subprocess
import time
from typing import Callable, Optional

from services import tuning
from services.logger.logger import setup_logger

logger = setup_logger("GpuCooldown")


def gpu_temperature() -> Optional[int]:
    """The hottest GPU's temperature in C, or None without nvidia-smi."""
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    temps = [int(t) for t in out.stdout.split() if t.strip().isdigit()]
    return max(temps) if out.returncode == 0 and temps else None


def wait_for_gpu_cooldown(
    reason: str = "",
    read_temperature: Callable[[], Optional[int]] = gpu_temperature,
    sleep: Callable[[float], None] = time.sleep,
) -> float:
    """Blocks while the GPU is at or above GPU_COOLDOWN_START_C, until it is
    down to GPU_COOLDOWN_RESUME_C or GPU_COOLDOWN_MAX_WAIT_SECONDS pass.
    Returns the seconds waited (0 when the GPU was cool or unreadable)."""
    temp = read_temperature()
    if temp is None or temp < tuning.GPU_COOLDOWN_START_C:
        return 0.0
    logger.info(
        "GPU at %dC - cooling down to %dC before %s.",
        temp, tuning.GPU_COOLDOWN_RESUME_C, reason or "the next GPU job",
    )
    waited = 0.0
    while waited < tuning.GPU_COOLDOWN_MAX_WAIT_SECONDS:
        sleep(tuning.GPU_COOLDOWN_POLL_SECONDS)
        waited += tuning.GPU_COOLDOWN_POLL_SECONDS
        temp = read_temperature()
        if temp is None or temp <= tuning.GPU_COOLDOWN_RESUME_C:
            break
    logger.info("GPU cooldown done after %.0fs (now %sC).", waited, temp)
    return waited
