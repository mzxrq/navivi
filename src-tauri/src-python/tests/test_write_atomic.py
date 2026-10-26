"""Trusted project files are swapped in whole, never left cut off (fix.md #3)."""

import json
import os

import pytest

from services import projectfiles
from services.projectfiles import write_json_atomic


def test_a_failed_write_keeps_the_old_file_and_leaves_no_temp(tmp_path, monkeypatch):
    target = tmp_path / "job_config.json"
    write_json_atomic(target, {"v": 1})

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(projectfiles.os, "replace", boom)
    with pytest.raises(OSError):
        write_json_atomic(target, {"v": 2})
    assert json.loads(target.read_text(encoding="utf-8")) == {"v": 1}
    assert os.listdir(tmp_path) == ["job_config.json"]


def test_a_briefly_locked_file_is_replaced_after_a_retry(tmp_path, monkeypatch):
    target = tmp_path / "timeline.json"
    real = os.replace
    calls = []

    def locked_once(src, dst):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError("in use")
        real(src, dst)

    monkeypatch.setattr(projectfiles.os, "replace", locked_once)
    monkeypatch.setattr(projectfiles.time, "sleep", lambda s: None)
    write_json_atomic(target, {"ok": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"ok": True} and len(calls) == 2


def test_a_tile_cache_setting_never_sweeps_the_project_folder(tmp_path, monkeypatch):
    import time

    from services.mapfetcher import maptile

    old_photo = tmp_path / "photo.jpg"
    old_photo.write_bytes(b"x")
    past = time.time() - 90 * 86400
    os.utime(old_photo, (past, past))
    monkeypatch.setattr(maptile.cx, "set_cache_dir", lambda d: None)
    downloader = maptile.TileDownloader({"directory_path": str(tmp_path), "settings": {"tile_cache_dir": "."}})
    assert downloader.cache_dir.name == "navivi_tiles"
    assert old_photo.exists()
