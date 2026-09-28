"""The waypoint editor's camera presets: one normalised key everywhere, a Wan
prompt for every moving preset, and "none" as a still photo (no ComfyUI)."""

from PIL import Image

from services import tuning
from services.vdoprocessing.camera_pan import STILL_PRESET, normalize_camera_pan
from services.vdoprocessing.img2vdo import AttractionVideoGenerator

# WaypointEditor.tsx cameraPans values.
EDITOR_PRESETS = ["none", "pan-left", "pan-right", "pan-up", "pan-down", "zoom-in", "zoom-out"]


class TestNormalize:
    def test_spellings_of_one_preset_agree(self):
        for hint in ("pan-right", "Pan Right", "pan_right", "panright", ["pan-right", "none"]):
            assert normalize_camera_pan(hint) == "panright"

    def test_nothing_gives_empty(self):
        assert normalize_camera_pan(None) == ""
        assert normalize_camera_pan([]) == ""


class TestEveryPresetIsCovered:
    def test_every_editor_preset_has_a_wan_prompt(self):
        for preset in EDITOR_PRESETS:
            assert normalize_camera_pan(preset) in tuning.COMFYUI_CAMERA_PAN_PROMPTS, preset


class TestStillPreset:
    def test_none_makes_a_still_clip_without_comfyui(self, tmp_path, monkeypatch):
        import services.vdoprocessing.comfyui_i2v_client as comfy

        def boom(*args, **kwargs):
            raise AssertionError("ComfyUI must not be used for the 'none' preset")

        monkeypatch.setattr(comfy.ComfyUII2VClient, "generate_clip", boom)
        img = tmp_path / "photo.jpg"
        Image.new("RGB", (800, 600), (120, 90, 60)).save(img)
        out = tmp_path / "clip.mp4"
        gen = AttractionVideoGenerator.__new__(AttractionVideoGenerator)
        gen.output_dir = tmp_path
        path = gen._generate_single_clip(str(img), STILL_PRESET, duration_sec=2.0, save_path=str(out))
        assert path == str(out) and out.stat().st_size > 0
