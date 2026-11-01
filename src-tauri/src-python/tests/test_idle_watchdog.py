"""The idle watchdog stops only the server it was started for (services/tts/idle_watchdog.py)."""

import subprocess
import sys

from services.tts import idle_watchdog as watchdog


def _run(monkeypatch, tmp_path, start_times):
    times = iter(start_times)
    killed = []
    monkeypatch.setattr(watchdog, "_started_at", lambda pid: next(times))
    monkeypatch.setattr(watchdog.time, "sleep", lambda s: None)
    monkeypatch.setattr(watchdog, "_kill", killed.append)
    monkeypatch.setattr(sys, "argv", ["idle_watchdog.py", "4242", str(tmp_path / "activity"), "0"])
    watchdog.main()
    return killed


def test_an_idle_server_is_stopped(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, [100.0, 100.0]) == [4242]


def test_a_pid_now_used_by_another_program_is_left_alone(monkeypatch, tmp_path):
    # The pipeline stopped the server between stages; Windows gave its PID to the next stage's ffmpeg.
    assert _run(monkeypatch, tmp_path, [100.0, 250.0]) == []


def test_a_finished_process_has_no_start_time():
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    assert watchdog._started_at(proc.pid) is None
