"""Waypoint photo upscale stage: which photos it touches, its 8 GB VRAM
guards, its cache, and how the upscaled paths reach (and stay out of)
job_config.json. ComfyUI and nvidia-smi are mocked; CPU only."""

import json
from pathlib import Path

import pytest
from PIL import Image

from services import render_estimate, tuning
from services.config.job_config import JobConfigManager
from services.config.upscaled_images import map_path
from services.vdoprocessing.videopipeline import upscale_step


def _photo(path: Path, size) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (120, 80, 40)).save(path)
    return str(path)


def _project(tmp_path, settings=None, **photos):
    images = {name: _photo(tmp_path / "assets" / "image" / f"{name}.jpg", size) for name, size in photos.items()}
    config = {
        "directory_path": str(tmp_path),
        "settings": settings or {},
        "waypoints": [{"label": n, "popup_image": [p], "images": [p]} for n, p in images.items()],
    }
    (tmp_path / "job_config.json").write_text(json.dumps(config), encoding="utf-8")
    return tmp_path / "job_config.json", images


class FakeClient:
    """Stands in for ComfyUII2VClient: a 4x nearest-neighbour 'model'."""

    def __init__(self):
        self.inputs = []
        self.freed = False

    def clear_queue(self):
        pass

    def run_image_graph(self, build_graph, image_path, output_node, output_path, timeout=None):
        graph = build_graph("uploaded.png")
        assert graph[output_node]["class_type"] == "SaveImage"
        assert graph["model"]["inputs"]["model_name"] == tuning.IMAGE_UPSCALE_MODEL
        with Image.open(image_path) as im:
            self.inputs.append(im.size)
            im.resize((im.width * 4, im.height * 4)).save(output_path)
        return output_path

    def free_memory(self):
        self.freed = True


@pytest.fixture
def gpu(monkeypatch):
    client = FakeClient()
    from services.vdoprocessing import comfyui_i2v_client

    monkeypatch.setattr(comfyui_i2v_client, "ComfyUII2VClient", lambda: client)
    monkeypatch.setattr(upscale_step, "_model_path", lambda: Path(__file__))
    monkeypatch.setattr(upscale_step, "free_vram_mb", lambda: 7000)
    from services import gpu_cooldown

    monkeypatch.setattr(gpu_cooldown, "wait_for_gpu_cooldown", lambda *a, **k: None)
    return client


def test_only_small_raster_photos_are_upscaled(tmp_path, gpu):
    cfg, images = _project(tmp_path, small=(800, 600), big=(1920, 1080))
    (tmp_path / "assets" / "image" / "logo.svg").write_text("<svg/>", encoding="utf-8")
    result = upscale_step.upscale_waypoint_images(str(cfg))

    assert result["gpu"] == 1 and result["skipped"] == 1
    assert list(result["map"]) == [str(Path(images["small"]).resolve())]
    assert not upscale_step.needs_upscale(str(tmp_path / "assets" / "image" / "logo.svg"))
    assert gpu.freed


def test_input_is_shrunk_so_4x_output_stays_within_max_side(tmp_path, gpu):
    cfg, _ = _project(tmp_path, wide=(1600, 900))
    result = upscale_step.upscale_waypoint_images(str(cfg))

    max_in = tuning.IMAGE_UPSCALE_MAX_SIDE // upscale_step.model_scale()
    assert max(gpu.inputs[0]) <= max_in
    with Image.open(next(iter(result["map"].values()))) as out:
        assert out.width >= tuning.IMAGE_UPSCALE_MIN_W and out.height >= tuning.IMAGE_UPSCALE_MIN_H
        assert max(out.size) <= tuning.IMAGE_UPSCALE_MAX_SIDE


def test_low_free_vram_falls_back_to_cpu(tmp_path, gpu, monkeypatch):
    monkeypatch.setattr(upscale_step, "free_vram_mb", lambda: tuning.IMAGE_UPSCALE_MIN_FREE_VRAM_MB - 1)
    cfg, _ = _project(tmp_path, small=(640, 480))
    result = upscale_step.upscale_waypoint_images(str(cfg))
    assert result["cpu"] == 1 and result["gpu"] == 0 and not gpu.inputs


def test_missing_model_uses_cpu_without_comfyui(tmp_path, gpu, monkeypatch):
    monkeypatch.setattr(upscale_step, "_model_path", lambda: tmp_path / "nope.pth")
    monkeypatch.setattr(upscale_step, "_download", lambda *a: (_ for _ in ()).throw(OSError("offline")))
    cfg, _ = _project(tmp_path, small=(640, 480))
    result = upscale_step.upscale_waypoint_images(str(cfg))
    assert result["cpu"] == 1 and not gpu.inputs and not gpu.freed


def test_comfyui_failure_falls_back_to_cpu(tmp_path, gpu, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("server down")

    monkeypatch.setattr(gpu, "run_image_graph", boom)
    cfg, _ = _project(tmp_path, small=(640, 480))
    assert upscale_step.upscale_waypoint_images(str(cfg))["cpu"] == 1


def test_unreadable_photo_keeps_the_original(tmp_path, gpu, monkeypatch):
    monkeypatch.setattr(upscale_step, "_gpu_upscale", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(upscale_step, "_cpu_upscale", lambda *a: (_ for _ in ()).throw(OSError()))
    cfg, _ = _project(tmp_path, small=(640, 480))
    result = upscale_step.upscale_waypoint_images(str(cfg))
    assert result["failed"] == 1 and result["map"] == {}


def test_cache_is_reused_and_force_rebuilds(tmp_path, gpu):
    cfg, _ = _project(tmp_path, small=(640, 480))
    upscale_step.upscale_waypoint_images(str(cfg))
    again = upscale_step.upscale_waypoint_images(str(cfg))
    assert again["cached"] == 1 and len(gpu.inputs) == 1
    forced = upscale_step.upscale_waypoint_images(str(cfg), force=True)
    assert forced["gpu"] == 1 and len(gpu.inputs) == 2


def test_disabled_or_fast_render_does_nothing(tmp_path, gpu):
    for settings in ({"skip_rich_media": True}, {"upscale_popup_images": False}):
        cfg, _ = _project(tmp_path, settings, small=(640, 480))
        result = upscale_step.upscale_waypoint_images(str(cfg))
        assert result["map"] == {} and not gpu.inputs
        assert not map_path(tmp_path).exists()


def test_job_config_swaps_paths_survives_reload_and_saves_originals(tmp_path, gpu):
    cfg, images = _project(tmp_path, small=(640, 480))
    result = upscale_step.upscale_waypoint_images(str(cfg))
    upscaled = next(iter(result["map"].values()))

    JobConfigManager(cfg)
    manager = JobConfigManager(cfg)
    wp = manager.get_waypoints()[0]
    assert wp["popup_image"] == [upscaled] and wp["images"] == [upscaled]

    manager.save()
    saved = json.loads(cfg.read_text(encoding="utf-8"))["waypoints"][0]
    assert saved["popup_image"] == [images["small"]]
    assert JobConfigManager(cfg).get_waypoints()[0]["popup_image"] == [upscaled]


def test_skip_rich_media_ignores_an_old_map(tmp_path, gpu):
    cfg, images = _project(tmp_path, small=(640, 480))
    upscale_step.upscale_waypoint_images(str(cfg))
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["settings"]["skip_rich_media"] = True
    cfg.write_text(json.dumps(data), encoding="utf-8")

    assert JobConfigManager(cfg).get_waypoints()[0]["popup_image"] == [images["small"]]

    from services.vdoprocessing.pydeckrecorder.routedata import load_route_from_config

    assert load_route_from_config(str(cfg))["waypoints"][0]["popup_image"] == [images["small"]]


def test_pydeck_loader_gets_upscaled_paths(tmp_path, gpu):
    cfg, _ = _project(tmp_path, small=(640, 480))
    upscaled = next(iter(upscale_step.upscale_waypoint_images(str(cfg))["map"].values()))
    from services.vdoprocessing.pydeckrecorder.routedata import load_route_from_config

    assert load_route_from_config(str(cfg))["waypoints"][0]["popup_image"] == [upscaled]


def test_estimate_counts_small_photos_and_maps_stage_numbers(tmp_path):
    cfg, _ = _project(tmp_path, small=(640, 480), big=(1920, 1080))
    config = json.loads(cfg.read_text(encoding="utf-8"))
    assert render_estimate.workload(config)["upscale"] == 1
    config["settings"]["skip_rich_media"] = True
    assert render_estimate.workload(config)["upscale"] == 0
    assert render_estimate.STAGES[3] == "upscale" and render_estimate.STAGES[4] == "attraction"


def _catalog(monkeypatch, tmp_path, payload: bytes, sha: str):
    import hashlib

    monkeypatch.setattr(upscale_step, "_model_path", lambda: tmp_path / "models" / "m.pth")
    monkeypatch.setattr(tuning, "IMAGE_UPSCALE_MODEL", "m.pth")
    monkeypatch.setattr(
        tuning, "IMAGE_UPSCALE_MODELS",
        {"m.pth": {"url": "https://example/m.pth", "sha256": sha or hashlib.sha256(payload).hexdigest(), "scale": 2}},
    )
    calls = []

    def fake_download(url, dest):
        calls.append(url)
        Path(dest).write_bytes(payload)

    monkeypatch.setattr(upscale_step, "_download", fake_download)
    return calls


def test_missing_model_is_downloaded_once_and_verified(tmp_path, monkeypatch):
    calls = _catalog(monkeypatch, tmp_path, b"weights", None)
    path = upscale_step.ensure_model()
    assert path == tmp_path / "models" / "m.pth" and path.read_bytes() == b"weights"
    assert upscale_step.ensure_model() == path and len(calls) == 1
    assert upscale_step.model_scale() == 2


def test_bad_checksum_leaves_no_model(tmp_path, monkeypatch):
    _catalog(monkeypatch, tmp_path, b"weights", "0" * 64)
    assert upscale_step.ensure_model() is None
    assert not list((tmp_path / "models").iterdir())


def test_unknown_model_name_is_not_downloaded(tmp_path, monkeypatch):
    calls = _catalog(monkeypatch, tmp_path, b"weights", None)
    monkeypatch.setattr(tuning, "IMAGE_UPSCALE_MODEL", "other.pth")
    assert upscale_step.ensure_model() is None and calls == []


def test_upscaled_photos_invalidate_the_route_render_caches(tmp_path, gpu):
    import pandas as pd

    from services.vdoprocessing.route2vdo import _leg_fingerprint_parts
    from services.vdoprocessing.route_inputs import photo_inputs_hash
    from services.vdoprocessing.spatial_renderer.overview import _overview_fingerprint_parts
    from services.vdoprocessing.videopipeline import render_step

    cfg, images = _project(tmp_path, small=(640, 480))
    route = {"route": pd.DataFrame({"latitude": [35.0, 35.1], "longitude": [139.0, 139.1]}), "summary": {}}
    before = render_step._checkpoint_parts(str(cfg), route, [], [])
    upscaled = next(iter(upscale_step.upscale_waypoint_images(str(cfg))["map"].values()))
    after = render_step._checkpoint_parts(str(cfg), route, [], [])

    assert before["route.photos"] != after["route.photos"]
    assert before["route.waypoints"] == after["route.waypoints"]
    assert "route.photos" in render_step.ROUTE_CHECKPOINT_PARTS

    leg = lambda img: _leg_fingerprint_parts([[35, 139]], "A", {"dest_popup_image": img, "walk_seconds": 9})
    assert leg(images["small"])["photos"] != leg(upscaled)["photos"]
    assert leg(upscaled)["photos"] == leg(upscaled)["photos"]

    ov = lambda img: _overview_fingerprint_parts({}, {}, tmp_path / "bg.png", {"popups": [{"data": {"popup_image": img}}]})
    assert ov(images["small"])["photos"] != ov(upscaled)["photos"]

    # Replacing a photo in place (same path) counts too.
    h1 = photo_inputs_hash([images["small"]])
    _photo(Path(images["small"]), (700, 500))
    import os
    os.utime(images["small"], (1, 1))
    assert photo_inputs_hash([images["small"]]) != h1


def test_model_output_is_kept_at_keep_scale_before_the_frame_fit(tmp_path, gpu, monkeypatch):
    seen = []
    real_cover = upscale_step.cover_size
    monkeypatch.setattr(upscale_step, "cover_size", lambda w, h: seen.append((w, h)) or real_cover(w, h))
    monkeypatch.setattr(tuning, "IMAGE_UPSCALE_KEEP_SCALE", 2)
    cfg, _ = _project(tmp_path, small=(500, 300))
    upscale_step.upscale_waypoint_images(str(cfg))
    assert gpu.inputs == [(500, 300)] and seen == [(1000, 600)]


def test_keep_scale_changes_the_cache_name(tmp_path, monkeypatch):
    src = _photo(tmp_path / "a.jpg", (300, 200))
    monkeypatch.setattr(tuning, "IMAGE_UPSCALE_KEEP_SCALE", 2)
    two = upscale_step.cached_path(tmp_path, src)
    monkeypatch.setattr(tuning, "IMAGE_UPSCALE_KEEP_SCALE", None)
    assert upscale_step.cached_path(tmp_path, src) != two


def test_every_catalog_model_is_pinned():
    for name, spec in tuning.IMAGE_UPSCALE_MODELS.items():
        assert "/resolve/" in spec["url"] and "/main/" not in spec["url"], name
        assert len(spec["sha256"]) == 64 and spec["scale"] in (1, 2, 4), name
    assert tuning.IMAGE_UPSCALE_MODEL in tuning.IMAGE_UPSCALE_MODELS
