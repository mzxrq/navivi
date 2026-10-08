"""One line of an FFmpeg concat-demuxer list file."""

import os


def concat_entry(path: str) -> str:
    """`file '<path>'` with forward slashes and a quote inside the path escaped as FFmpeg expects (`'\\''`).

    Without the escape a folder such as C:\\Users\\O'Brien\\... makes FFmpeg reject the whole list."""
    safe = os.path.abspath(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{safe}'\n"
