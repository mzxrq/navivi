"""Progress lines for the engine installers.

The installers run as one Python call, so the app only sees what they print on stderr. Each step prints
`[progress] <done>/<total>|<label>`; Rust forwards stderr lines as `blueprint-log` events and the install
toast/button read these lines (src/services/installs.ts parses the same format)."""

import sys

_done = 0
_total = 1


def begin(total: int) -> None:
    global _done, _total
    _done, _total = 0, max(1, total)
    # Not a counted step: the first real step announces 0/total, the last one (total-1)/total, and 100% comes when the call returns.
    print(f"[progress] 0/{_total}|Starting", file=sys.stderr, flush=True)


def step(label: str) -> None:
    """Announce the step that is about to start; everything before it counts as done."""
    global _done
    print(f"[progress] {min(_done, _total)}/{_total}|{label}", file=sys.stderr, flush=True)
    _done += 1
