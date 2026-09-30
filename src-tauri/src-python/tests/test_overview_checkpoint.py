import copy

import numpy as np

from services.vdoprocessing.spatial_renderer.overview import (
    _fingerprint_hash,
    _overview_fingerprint_parts,
)


class _Thing:
    pass


def _inputs(tmp_path):
    bg = tmp_path / "bg.png"
    bg.write_bytes(b"png-bytes")
    config = {"fps": 30, "checkpoint_enabled": True, "overview_rerender": False, "obj": _Thing()}
    job_config = {
        "updated_at": "2026-09-30T10:00:00Z",
        "waypoints": [{"label": "A", "narration": "hello", "popup_image": ["a.jpg"]}],
    }
    args = {"points": np.array([[1, 2], [3, 4]]), "popups": [{"label": "A", "audio_duration": 5.0}]}
    return config, job_config, bg, args


def test_fingerprint_is_stable(tmp_path):
    config, job_config, bg, args = _inputs(tmp_path)
    a = _overview_fingerprint_parts(config, job_config, bg, args)
    b = _overview_fingerprint_parts(dict(config, obj=_Thing()), job_config, bg, args)
    assert _fingerprint_hash(a) == _fingerprint_hash(b)


def test_leg_only_fields_and_flags_are_ignored(tmp_path):
    config, job_config, bg, args = _inputs(tmp_path)
    before = _overview_fingerprint_parts(config, job_config, bg, args)
    edited = copy.deepcopy(job_config)
    edited["waypoints"][0]["narration"] = "changed"
    edited["updated_at"] = "later"
    after = _overview_fingerprint_parts(dict(config, overview_rerender=True), edited, bg, args)
    assert before == after


def test_real_changes_are_named(tmp_path):
    config, job_config, bg, args = _inputs(tmp_path)
    before = _overview_fingerprint_parts(config, job_config, bg, args)
    edited = copy.deepcopy(job_config)
    edited["waypoints"][0]["popup_image"] = ["b.jpg"]
    bg.write_bytes(b"other-map")
    after = _overview_fingerprint_parts(
        config, edited, bg, dict(args, popups=[{"label": "A", "audio_duration": 6.0}])
    )
    changed = {k for k in before if before[k] != after.get(k)}
    assert changed == {"background_image", "arg.popups", "job_config.waypoints[0]"}
