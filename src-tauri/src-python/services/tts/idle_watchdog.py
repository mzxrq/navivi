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


def _process_alive(pid: int) -> bool:
    if os.name == "nt":
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}"],
            capture_output=True,
            text=True,
        )
        return str(pid) in result.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by someone else
    return True


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
    # Frequent enough to shut down close to the deadline, infrequent enough
    # not to matter as background overhead — never faster than 5s, never
    # slower than 30s regardless of how long idle_timeout itself is.
    poll_interval = min(30.0, max(5.0, idle_timeout / 10))

    while True:
        time.sleep(poll_interval)

        if not _process_alive(pid):
            return  # server already gone (crashed, or killed some other way)

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
