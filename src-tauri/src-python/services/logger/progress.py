"""Shared live-status tracker for the CLI and rendering engines.

Both main.py's CLI wrapper functions AND the actual production pipeline
(services.vdoprocessing.videopipeline, route2vdo.py, the spatial_renderer's
per-leg route rendering) import the same `tracker` singleton here, so a
waypoint being processed deep inside the real render engine shows up with
the exact same "[mm:ss] [n/N] ..." status line as running main.py's test_*
commands directly — one live-updating line per process, not a separate
progress mechanism per module.
"""

import sys
import time
from typing import Optional


class StepTracker:
    """Shows what the pipeline is doing right now as a single in-place
    terminal line — no persistent step log, just "what's happening at this
    moment" (e.g. which waypoint is currently being processed), overwritten
    in place and erased once that work is done rather than piling up one
    line per step/item. Every line is stamped with elapsed time since the
    process started, and — for a multi-stage run (see `stage`) — an overall
    "[n/N]" counter, so a long run still reads as "how far along am I"
    rather than just "what's happening right this second".

    Deliberately silent unless stderr is a live terminal — when Tauri spawns
    this script, stderr is a pipe (not a tty), so this never emits ANSI
    control codes into the render-error stream or JSON parsed from stdout."""

    def __init__(self) -> None:
        # [NOTE] [Core] stderr is a pipe (not a tty) when Tauri spawns this script, so ANSI control codes are only emitted in an interactive terminal.
        self._live = sys.stderr.isatty()
        self._open = False
        self._start = time.monotonic()
        self._stage_num = 0
        self._stage_total = 0

    def elapsed(self) -> str:
        secs = int(time.monotonic() - self._start)
        return f"{secs // 60:02d}:{secs % 60:02d}"

    def stage(self, name: str, total: Optional[int] = None) -> None:
        """Marks the start of a new top-level pipeline stage. `total` (the
        overall stage count) only needs to be passed once, by whichever
        caller knows it up front — every show() call after this, including
        ones made deep inside a per-waypoint loop in a totally different
        module, then carries this stage's "[n/N]" until the next stage()
        call, since the tracker is a single shared instance for the whole
        process."""
        if total is not None:
            self._stage_total = total
        self._stage_num += 1
        self.show(name)

    def show(self, text: str) -> None:
        prefix = f"[{self.elapsed()}]"
        if self._stage_total:
            prefix += f" [{self._stage_num}/{self._stage_total}]"
        line = f"{prefix} {text}"
        if self._live:
            if self._open:
                sys.stderr.write("\r\x1b[2K")
            sys.stderr.write(line)
            self._open = True
        else:
            sys.stderr.write(f"{line}\n")
        sys.stderr.flush()

    def clear(self) -> None:
        if self._live and self._open:
            sys.stderr.write("\r\x1b[2K")
            sys.stderr.flush()
        self._open = False


# [NOTE] [Core] One shared instance per process — imported by main.py and by the
# production render engine (videopipeline/*, route2vdo.py, spatial_renderer)
# alike, so all of them report progress on the same live status line.
tracker = StepTracker()
