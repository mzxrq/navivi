"""Sequential extension in comfyui_i2v_client: how many segments a clip gets,
and how the extra segments are wired into the one ComfyUI graph. Pure graph
building - no ComfyUI server involved."""

import pytest

from services import tuning
from services.vdoprocessing import comfyui_i2v_client as client_mod
from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

SEGMENT_SEC = tuning.COMFYUI_MAX_FRAMES / tuning.COMFYUI_GEN_FPS


def _graph(segments):
    return ComfyUII2VClient.__new__(ComfyUII2VClient)._build_graph(
        "in.png", "zoom-in", tuning.COMFYUI_MAX_FRAMES, "attraction/x", segments
    )


class TestResolveSegments:
    def test_short_clip_is_one_segment_sized_to_it(self):
        count, length = client_mod._resolve_segments(2.0)
        assert count == 1
        assert length == client_mod._resolve_frame_length(2.0)

    def test_long_narration_gets_enough_full_segments(self, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_EXTEND_MAX_SEGMENTS", None)
        count, length = client_mod._resolve_segments(SEGMENT_SEC * 1.5)
        assert count == 2
        assert length == tuning.COMFYUI_MAX_FRAMES

    def test_default_caps_a_photo_at_the_configured_segments(self):
        count, length = client_mod._resolve_segments(60.0)
        assert count == tuning.COMFYUI_EXTEND_MAX_SEGMENTS
        assert length == tuning.COMFYUI_MAX_FRAMES

    def test_uncapped_chains_the_whole_narration(self, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_EXTEND_MAX_SEGMENTS", None)
        count, length = client_mod._resolve_segments(SEGMENT_SEC * 6.2)
        assert count == 7  # ceil(6.2), no ceiling applied
        assert length == tuning.COMFYUI_MAX_FRAMES

    def test_a_number_still_caps_it(self, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_EXTEND_MAX_SEGMENTS", 2)
        count, _ = client_mod._resolve_segments(600.0)
        assert count == 2

    def test_one_turns_extension_off(self, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_EXTEND_MAX_SEGMENTS", 1)
        count, length = client_mod._resolve_segments(600.0)
        assert count == 1
        assert length == tuning.COMFYUI_MAX_FRAMES


class TestBuildGraph:
    @pytest.fixture(autouse=True)
    def _five_b(self, monkeypatch):
        monkeypatch.setattr(tuning, "COMFYUI_MODEL", "5b")

    def test_one_segment_is_the_plain_template(self):
        graph = _graph(1)
        assert not [k for k in graph if k.startswith("ext")]
        assert graph["57"]["inputs"]["images"] == ["8", 0]

    def test_each_segment_starts_from_the_previous_last_frame(self):
        graph = _graph(3)
        assert graph["ext1_last"]["inputs"]["image"] == ["8", 0]
        assert graph["ext1_last"]["inputs"]["batch_index"] == -1
        assert graph["ext2_last"]["inputs"]["image"] == ["ext1_decode", 0]
        assert graph["ext2_latent"]["inputs"]["start_image"] == ["ext2_last", 0]
        assert graph["ext2_sample"]["inputs"]["latent_image"] == ["ext2_latent", 0]
        assert graph["ext2_decode"]["inputs"]["samples"] == ["ext2_sample", 0]

    def test_repeated_start_frame_is_dropped_and_all_segments_batched(self):
        graph = _graph(3)
        assert graph["ext1_trim"]["inputs"]["batch_index"] == 1
        batch = graph["ext_batch"]
        assert batch["class_type"] == "BatchImagesNode"
        assert batch["inputs"] == {
            "images.image0": ["8", 0],
            "images.image1": ["ext1_trim", 0],
            "images.image2": ["ext2_trim", 0],
        }
        assert graph["57"]["inputs"]["images"] == ["ext_batch", 0]

    def test_every_segment_gets_its_own_seed(self):
        graph = _graph(3)
        seeds = {graph[k]["inputs"]["seed"] for k in ("3", "ext1_sample", "ext2_sample")}
        assert len(seeds) == 3

    def test_every_reference_points_at_a_real_node(self):
        graph = _graph(4)
        for node in graph.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    assert value[0] in graph, value


class TestMotionPrompt:
    def test_hyphenated_hint_matches_its_preset(self):
        for hint in ("zoom-in", "Zoom In", "zoom_in", "zoomin"):
            assert client_mod._resolve_motion_prompt(hint) == tuning.COMFYUI_CAMERA_PAN_PROMPTS["zoomin"]

    def test_unknown_hint_is_treated_as_a_scene_description(self):
        prompt = client_mod._resolve_motion_prompt("old shrine gate")
        assert prompt.startswith("old shrine gate, ")


class TestA14BGraph:
    def _graph(self, monkeypatch, segments=1):
        monkeypatch.setattr(tuning, "COMFYUI_MODEL", "a14b")
        return _graph(segments)

    def test_high_expert_hands_its_noisy_latent_to_the_low_one(self, monkeypatch):
        graph = self._graph(monkeypatch)
        high, low = graph["3"]["inputs"], graph["3_low"]["inputs"]
        assert high["model"] == ["shift_high", 0] and low["model"] == ["shift_low", 0]
        assert high["return_with_leftover_noise"] == "enable" and low["add_noise"] == "disable"
        assert high["end_at_step"] == low["start_at_step"] == tuning.COMFYUI_A14B_SPLIT_STEP
        assert low["latent_image"] == ["3", 0]
        assert graph["8"]["inputs"]["samples"] == ["3_low", 0]

    def test_each_expert_loads_its_own_gguf_and_lora(self, monkeypatch):
        graph = self._graph(monkeypatch)
        assert graph["unet_high"]["inputs"]["unet_name"] == tuning.COMFYUI_A14B_HIGH_UNET_NAME
        assert graph["unet_low"]["inputs"]["unet_name"] == tuning.COMFYUI_A14B_LOW_UNET_NAME
        assert graph["lora_high"]["inputs"]["model"] == ["unet_high", 0]
        assert graph["shift_low"]["inputs"]["model"] == ["lora_low", 0]

    def test_conditioning_and_latent_come_from_wan_image_to_video(self, monkeypatch):
        graph = self._graph(monkeypatch)
        assert graph["55"]["class_type"] == "WanImageToVideo"
        assert graph["55"]["inputs"]["length"] == tuning.COMFYUI_MAX_FRAMES
        assert graph["3"]["inputs"]["positive"] == ["55", 0]
        assert graph["3"]["inputs"]["latent_image"] == ["55", 2]
        assert isinstance(graph["3"]["inputs"]["noise_seed"], int)

    def test_every_reference_points_at_a_real_node(self, monkeypatch):
        graph = self._graph(monkeypatch)
        for node in graph.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    assert value[0] in graph, value

    def test_segments_are_never_unrolled(self, monkeypatch):
        with pytest.raises(ValueError):
            self._graph(monkeypatch, segments=2)


class TestFunCameraGraph:
    def _graph(self, monkeypatch, pose="Pan Right", segments=1):
        monkeypatch.setattr(tuning, "COMFYUI_MODEL", "fun_camera")
        return ComfyUII2VClient.__new__(ComfyUII2VClient)._build_graph(
            "in.png", "pan-right", 81, "attraction/x", segments, pose
        )

    def test_the_preset_becomes_the_camera_path(self, monkeypatch):
        graph = self._graph(monkeypatch, "Zoom Out")
        camera = graph["camera"]["inputs"]
        assert camera["camera_pose"] == "Zoom Out" and camera["length"] == 81
        assert graph["55"]["class_type"] == "WanCameraImageToVideo"
        assert graph["55"]["inputs"]["camera_conditions"] == ["camera", 0]
        assert graph["55"]["inputs"]["length"] == ["camera", 3]

    def test_the_photo_is_also_given_as_clip_vision(self, monkeypatch):
        graph = self._graph(monkeypatch)
        assert graph["clip_vision_encode"]["inputs"]["image"] == ["56", 0]
        assert graph["55"]["inputs"]["clip_vision_output"] == ["clip_vision_encode", 0]

    def test_sampler_uses_its_conditioning_and_latent(self, monkeypatch):
        graph = self._graph(monkeypatch)
        sampler = graph["3"]["inputs"]
        assert sampler["model"] == ["48", 0] and sampler["latent_image"] == ["55", 2]
        assert sampler["positive"] == ["55", 0] and sampler["negative"] == ["55", 1]
        assert isinstance(sampler["seed"], int)

    def test_every_reference_points_at_a_real_node(self, monkeypatch):
        graph = self._graph(monkeypatch)
        for node in graph.values():
            for value in node["inputs"].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    assert value[0] in graph, value

    def test_segments_are_never_unrolled(self, monkeypatch):
        with pytest.raises(ValueError):
            self._graph(monkeypatch, segments=2)


class TestCameraPose:
    def test_every_editor_preset_has_a_camera_move(self):
        for hint, pose in (("pan-left", "Pan Left"), ("Pan Up", "Pan Up"), ("pan_down", "Pan Down"),
                           ("zoom-in", "Zoom In"), ("zoomout", "Zoom Out"), ("pan-right", "Pan Right")):
            assert client_mod._resolve_camera_pose(hint) == pose

    def test_anything_else_holds_the_camera_still(self):
        assert client_mod._resolve_camera_pose("old shrine gate") == "Static"
        assert client_mod._resolve_camera_pose(None) == "Static"
