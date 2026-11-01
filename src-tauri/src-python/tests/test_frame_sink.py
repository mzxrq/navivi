"""A leg clip whose ffmpeg fails must not leave an older clip looking like this render's result."""

import asyncio

import pytest

from services.vdoprocessing.pydeckrecorder.frame_sink import FrameSink


class _Proc:
    def __init__(self, code):
        self.code, self.returncode, self.killed = code, None, False

        class _In:
            def close(self):
                pass

        self.stdin = _In()

    async def wait(self):
        self.returncode = -9 if self.killed else self.code
        return self.returncode

    def kill(self):
        self.killed = True


def _sink(tmp_path, code):
    sink = FrameSink.__new__(FrameSink)
    temp = tmp_path / "leg.tmp.mp4"
    temp.write_bytes(b"new")
    sink.proc_ref = {"proc": _Proc(code), "temp_path": str(temp), "real_path": str(tmp_path / "leg.mp4")}
    return sink, temp


def test_failed_encode_raises_and_keeps_nothing_new(tmp_path):
    (tmp_path / "leg.mp4").write_bytes(b"old")
    sink, temp = _sink(tmp_path, 1)
    with pytest.raises(RuntimeError):
        asyncio.run(sink.finalize())
    assert not temp.exists() and (tmp_path / "leg.mp4").read_bytes() == b"old"


def test_abort_kills_ffmpeg_and_removes_its_temp(tmp_path):
    sink, temp = _sink(tmp_path, 0)
    asyncio.run(sink.abort())
    assert sink.proc_ref["proc"].killed and not temp.exists()
