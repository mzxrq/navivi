"""Sequential extension in comfyui_i2v_client: how many segments a clip gets,
and how the extra segments are wired into the one ComfyUI graph. Pure graph
building - no ComfyUI server involved."""

from services import tuning
from services.vdoprocessing import comfyui_i2v_client as client_mod
from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient

SEGMENT_SEC = tuning.COMFYUI_MAX_FRAMES / tuning.COMFYUI_FPS


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

    def test_uncapped_by_default_chains_the_whole_narration(self, monkeypatch):
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
