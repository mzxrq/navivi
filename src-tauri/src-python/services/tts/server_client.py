"""Lifecycle of a local TTS server subprocess: start it on demand, share it across processes, stop it.

The server a client talks to is a separate, bundled process (see bin/Irodori-TTS-Server/README.md).
It is auto-started as a subprocess the first time a request finds the connection refused/closed,
using its own already-synced .venv so nothing here depends on `uv` being on PATH. It is kept running
afterward (not torn down when this process exits) since it's slow to start — it loads a real model —
and every later call in the same session, or a later main.py invocation, should find it already warm.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional
from urllib.parse import urlsplit

import httpx

from services.logger.logger import setup_logger

logger = setup_logger("TTSEngine")

DEFAULT_SERVER_PORT = 8088
HEALTH_TIMEOUT_SECONDS = 3.0
PID_LOOKUP_TIMEOUT_SECONDS = 5
PID_COMMAND_LINE_TIMEOUT_SECONDS = 15


def _kill_process_tree(pid: int) -> None:
    """Same approach as idle_watchdog.py's _kill — /T also takes down the
    child process(es) a server subprocess may have spawned, not just the
    immediate PID."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        import signal
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def _detached_popen_kwargs() -> Dict[str, Any]:
    """Popen kwargs that let a child outlive a short-lived `python main.py ...` CLI invocation.

    CREATE_NEW_PROCESS_GROUP: not torn down (or fighting over Ctrl+C) with the parent.
    CREATE_NO_WINDOW (not DETACHED_PROCESS): a fully detached process has NO console at all, which some
    Fortran/MKL-linked scientific-Python dependencies crash under on Windows ("forrtl: error (200):
    program aborting due to window-CLOSE event") — CREATE_NO_WINDOW still shows no visible window but
    keeps a (hidden) console allocated.
    """
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


class _LocalServerClient:
    """Starts, shares and stops one local TTS server subprocess.

    A subclass supplies the server's location (`_SERVER_DIR`, `_SERVER_VENV_PYTHON`, `_ACTIVITY_FILE`,
    `_PIDFILE`, `_PROCESS_MARKER`, `_SERVER_NAME`), its own `_server_process` slot, and implements
    `_spawn_server` and `_missing_server_message`.
    """

    _SERVER_DIR: ClassVar[Path]
    _SERVER_VENV_PYTHON: ClassVar[Path]
    _ACTIVITY_FILE: ClassVar[Path]
    _PIDFILE: ClassVar[Path]
    # What the server's command line contains, to tell it from an unrelated process that reused a stale pidfile's PID.
    _PROCESS_MARKER: ClassVar[str]
    _SERVER_NAME: ClassVar[str]

    # The server's own IRODORI_MODEL_LOAD_TIMEOUT defaults to 300s for loading an already-downloaded model —
    # and the FIRST run also has to download the model from Hugging Face before that even starts, which isn't
    # bounded by that setting at all. Generous on purpose: giving up too early on a legitimately slow
    # first-time download/load is a much worse failure mode than this function just taking a while.
    _SERVER_START_TIMEOUT_SECONDS: ClassVar[float] = 600.0
    _SERVER_POLL_INTERVAL_SECONDS: ClassVar[float] = 1.0

    # How long the server can sit unused before the watchdog (see idle_watchdog.py) shuts it down.
    # Auto-starting it is only worth doing if it doesn't also sit there forever afterward, especially since
    # it holds a loaded model — 10 minutes covers the gaps between waypoints in a single pipeline run
    # without shutting down mid-job, short enough not to waste resources long after the last run finished.
    _IDLE_TIMEOUT_SECONDS: ClassVar[float] = 600.0

    # Class-level: one server subprocess (and one watchdog) is enough for every client instance/every caller
    # in this process (main.py's tts/tts-all/attraction commands, and the real audio_step.py pipeline, can
    # each construct their own client). Each engine class redefines it so engines never share a handle.
    _server_process: Optional[subprocess.Popen] = None

    base_url: str

    def _spawn_server(self, port: int, popen_kwargs: Dict[str, Any]) -> subprocess.Popen:
        raise NotImplementedError

    def _missing_server_message(self) -> str:
        raise NotImplementedError

    def _health_url(self) -> str:
        parts = urlsplit(self.base_url)
        return f"{parts.scheme}://{parts.netloc}/health"

    async def _is_server_up(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self._health_url(), timeout=HEALTH_TIMEOUT_SECONDS)
                return response.status_code == 200
        except httpx.HTTPError:
            return False

    @staticmethod
    def _pid_is_alive(pid: int) -> bool:
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}"],
                    capture_output=True, text=True, timeout=PID_LOOKUP_TIMEOUT_SECONDS,
                )
                return str(pid) in result.stdout
            except Exception:
                return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    @classmethod
    def _pidfile_pid(cls) -> Optional[int]:
        try:
            return int(cls._PIDFILE.read_text().strip())
        except (OSError, ValueError):
            return None

    @staticmethod
    def _pid_command_line(pid: int) -> Optional[str]:
        """The command line of a running process, or None when it cannot be read (no PowerShell, a timeout, no /proc)."""
        try:
            if os.name == "nt":
                return subprocess.run(
                    ["powershell", "-NoProfile", "-Command",
                     f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                    capture_output=True, text=True, timeout=PID_COMMAND_LINE_TIMEOUT_SECONDS,
                ).stdout
            return Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
        except Exception:
            return None

    @classmethod
    def _pid_is_server(cls, pid: int) -> bool:
        """Guards against a stale pidfile whose PID now belongs to something else."""
        return cls._PROCESS_MARKER in (cls._pid_command_line(pid) or "")

    @classmethod
    def _other_process_is_starting_server(cls) -> bool:
        """Reads the pidfile a spawning process writes right after Popen —
        True if some other still-alive process claims to already be
        starting the server, so this one should just wait instead of
        racing to spawn a second copy.

        [HACK] [TTS] Windows hands PIDs out again quickly, and a crash or hard kill leaves the pidfile behind: a live PID is only
        believed when its command line really is the server's. A PID that is alive but belongs to something else is a stale file
        (removed here, so the server is started); if the command line cannot be read at all the PID is trusted, because starting a
        second copy next to a healthy one is the worse mistake."""
        pid = cls._pidfile_pid()
        if pid is None or not cls._pid_is_alive(pid):
            return False
        command_line = cls._pid_command_line(pid)
        if command_line is None or cls._PROCESS_MARKER in command_line:
            return True
        logger.info("%s pidfile names PID %s, which is another program now; ignoring it.", cls._SERVER_NAME, pid)
        cls._PIDFILE.unlink(missing_ok=True)
        return False

    @classmethod
    def _own_server_alive(cls) -> bool:
        process = cls._server_process
        return process is not None and process.poll() is None

    def _touch_activity(self) -> None:
        """Marks the server as just-used — read by idle_watchdog.py (as the
        activity file's mtime) to decide whether it's been idle long enough
        to shut down. Failure here (e.g. read-only filesystem) shouldn't
        break an otherwise-successful TTS call, just the idle-shutdown
        feature, so it's swallowed rather than raised."""
        try:
            self._ACTIVITY_FILE.touch()
        except OSError:
            pass

    def _start_idle_watchdog(self, server_pid: int) -> None:
        """Spawns idle_watchdog.py as its own detached process — not a
        thread or asyncio task in THIS process, because this process (a
        `python main.py ...` CLI invocation) is typically short-lived and
        exits long before 10 minutes of idle TTS server time would ever
        elapse; the watchdog has to keep running independently of whatever
        started the server to actually catch that."""
        watchdog_script = Path(__file__).resolve().parent / "idle_watchdog.py"
        subprocess.Popen(
            [
                sys.executable, str(watchdog_script),
                str(server_pid), str(self._ACTIVITY_FILE),
                str(self._IDLE_TIMEOUT_SECONDS),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **_detached_popen_kwargs(),
        )

    def _start_server(self) -> None:
        """Spawns the server, records its pid for other processes, and starts the idle watchdog."""
        logger.info(
            "Irodori TTS server not reachable at %s — starting it as a "
            "subprocess (this can take a while on first run while it "
            "downloads/loads the model)...",
            self.base_url,
        )
        port = urlsplit(self.base_url).port or DEFAULT_SERVER_PORT
        type(self)._server_process = self._spawn_server(port, _detached_popen_kwargs())
        self._PIDFILE.write_text(str(type(self)._server_process.pid))
        # Baseline activity timestamp so the watchdog's idle clock
        # starts from "just launched", not from whatever this file's
        # mtime happened to be left at by a previous run.
        self._touch_activity()
        self._start_idle_watchdog(type(self)._server_process.pid)

    async def _wait_until_healthy(self) -> None:
        """Polls /health until the server answers; raises if it dies while starting or never comes up."""
        deadline = time.monotonic() + self._SERVER_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if await self._is_server_up():
                logger.info("Irodori TTS server is up at %s.", self.base_url)
                return
            process = type(self)._server_process
            if process is not None and process.poll() is not None:
                raise RuntimeError(
                    "Irodori TTS server subprocess exited while starting up — "
                    f"see {self._SERVER_DIR / 'server.log'} for details."
                )
            # Started by another process (a preview, another stage): if that server's PID is gone it died while loading, and waiting
            # out the rest of the (many minutes) timeout would only delay the same error.
            if process is None:
                other = self._pidfile_pid()
                if other is not None and not self._pid_is_alive(other):
                    raise RuntimeError(
                        f"The {self._SERVER_NAME} server another process was starting stopped before it was ready — "
                        f"see {self._SERVER_DIR / 'server.log'} for details."
                    )
            await asyncio.sleep(self._SERVER_POLL_INTERVAL_SECONDS)

        raise RuntimeError(
            f"Irodori TTS server did not become healthy within "
            f"{self._SERVER_START_TIMEOUT_SECONDS:.0f}s of starting."
        )

    async def _ensure_server_running(self) -> None:
        """Starts the local TTS server as a subprocess if it isn't
        already reachable, then waits for its /health endpoint to come up.
        Raises RuntimeError if it can't be found/started or never becomes
        healthy in time — callers should let that propagate rather than
        silently continuing to a request that would just fail the same way."""
        # Check health FIRST — a fresh client in a brand new `main.py` process always starts with
        # _server_process == None, so without this check every single invocation would fall straight
        # into the spawn branch below even when a server from an earlier invocation is already up and healthy.
        if await self._is_server_up():
            logger.info("Irodori TTS server already up at %s.", self.base_url)
            return

        if not self._SERVER_VENV_PYTHON.exists():
            raise RuntimeError(self._missing_server_message())

        if not self._own_server_alive():
            if self._other_process_is_starting_server():
                logger.info(
                    "Another process is already starting the Irodori TTS "
                    "server — waiting for it instead of starting a second copy."
                )
            else:
                self._start_server()

        await self._wait_until_healthy()

    @classmethod
    def stop_server(cls) -> None:
        """Explicitly terminates the TTS server now, rather than waiting on
        its idle timeout. For a single process/job that runs TTS generation
        fully up front and then a separate GPU-heavy step afterward (see
        main.py's test_all) — the 10-minute idle timeout was sized for gaps
        BETWEEN waypoints within one job, not for handing the GPU off to a
        different consumer right after TTS finishes, so left alone the
        server stays fully loaded and fights that next step for VRAM for
        most/all of the idle window. Only effective if THIS process is the
        one that started the server (holds the live subprocess handle) — a
        server left running from an earlier process can't be reached here;
        it'll fall back to its own idle-timeout watchdog as before."""
        if cls._server_process is not None and cls._server_process.poll() is None:
            logger.info("Stopping Irodori TTS server (%s) to free its resources for the next step.", cls._server_process.pid)
            _kill_process_tree(cls._server_process.pid)
            cls._server_process = None
            cls._PIDFILE.unlink(missing_ok=True)
            return
        # Started by another process (e.g. a voice preview): stop it via the pidfile.
        try:
            pid = int(cls._PIDFILE.read_text().strip())
        except (OSError, ValueError):
            return
        if cls._pid_is_server(pid):
            logger.info("Stopping Irodori TTS server (%s) started by another process.", pid)
            _kill_process_tree(pid)
        cls._PIDFILE.unlink(missing_ok=True)
