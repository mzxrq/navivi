"""Standalone idle-shutdown watchdog for the local Irodori TTS server.

Terminates the server process after IDLE_TIMEOUT_SECONDS with no activity,
tracked via ACTIVITY_FILE's mtime (touched by IrodoriTTSClient on every
successful request — see ttsengine.py). Run as its own detached process
(spawned by IrodoriTTSClient._ensure_server_running) so it keeps watching
even after the short-lived main.py CLI process that started the server has
already exited — the server and the process that happened to start it are
not the same lifetime.

Usage: python idle_watchdog.py <server_pid> <activity_file> <idle_timeout_seconds>
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Optional

import psutil


# [NOTE] [Util] A PID plus its start time names one process: the pipeline stops the server between stages without
# stopping this watchdog, and Windows soon hands the PID to another program (an ffmpeg or Chromium of the next stage).
def _started_at(pid: int) -> Optional[float]:
    try:
        return psutil.Process(pid).create_time()
    except psutil.Error:
        return None


# [HACK] [Util] Force-kills the process tree; taskkill /T/F is the Windows equivalent of a hard SIGTERM to a whole process group
def _kill(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        import signal

        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def main() -> None:
    pid = int(sys.argv[1])
    activity_file = sys.argv[2]
    idle_timeout = float(sys.argv[3])
    # [NOTE] [TTS] Frequent enough to shut down close to the deadline, infrequent enough
    # not to matter as background overhead — never faster than 5s, never
    # slower than 30s regardless of how long idle_timeout itself is.
    poll_interval = min(30.0, max(5.0, idle_timeout / 10))
    started = _started_at(pid)
    if started is None:
        return

    # [NOTE] [Core] Runs forever as its own detached process until either the watched
    # server dies on its own or this loop kills it for being idle too long.
    while True:
        time.sleep(poll_interval)

        if _started_at(pid) != started:
            return  # server already gone (crashed, or stopped by the pipeline), even if its PID is in use again

        try:
            last_active = os.path.getmtime(activity_file)
        except OSError:
            # No activity recorded yet — treat "now" as the baseline rather
            # than killing a server that only just finished starting.
            last_active = time.time()

        if time.time() - last_active >= idle_timeout:
            _kill(pid)
            return


if __name__ == "__main__":
    main()
