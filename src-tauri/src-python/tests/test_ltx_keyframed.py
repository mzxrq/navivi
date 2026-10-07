"""LTXV-13B keyframed moves (2026-10-02): "pan right" is made by LTXV between
two real crops of the photo, with the 3D photo as the fallback."""

import json

import cv2
import numpy as np

from services import tuning
from services.config.job_config import JobConfigManager
from services.vdoprocessing import img2vdo, ltx_keyframed
from services.vdoprocessing.img2vdo import AttractionVideoGenerator


def _marked_photo(path):
    photo = np.full((900, 1600, 3), 128, np.uint8)
    photo[:, :200] = (0, 0, 255)    # red strip at the far left
    photo[:, -200:] = (0, 255, 0)   # green strip at the far right
    cv2.imwrite(str(path), photo)
    return str(path)


def _has(img, bgr):
    return bool(np.all(np.abs(img.astype(int) - bgr) < 40, axis=2).any())


class TestCropKeyframes:
    def test_pan_right_goes_from_the_left_crop_to_the_right_crop(self, tmp_path):
        first, last = ltx_keyframed.crop_keyframes(_marked_photo(tmp_path / "p.png"), "panright", tmp_path / "k")
        a, b = cv2.imread(first), cv2.imread(last)
        assert a.shape[:2] == (tuning.LTXV_HEIGHT, tuning.LTXV_WIDTH) == b.shape[:2]
        assert _has(a, (0, 0, 255)) and not _has(a, (0, 255, 0))
        assert _has(b, (0, 255, 0)) and not _has(b, (0, 0, 255))

    def test_pan_left_is_the_reverse(self, tmp_path):
        first, last = ltx_keyframed.crop_keyframes(_marked_photo(tmp_path / "p.png"), "panleft", tmp_path / "k")
        assert _has(cv2.imread(first), (0, 255, 0)) and _has(cv2.imread(last), (0, 0, 255))


class TestRects:
    W, H = 1920, 1447

    def _inside(self, r):
        x, y, cw, ch = r
        return 0 <= x and 0 <= y and x + cw <= self.W and y + ch <= self.H

    def test_every_move_stays_in_the_photo_at_the_ltx_aspect(self):
        aspect = tuning.LTXV_WIDTH / tuning.LTXV_HEIGHT
        for move in tuning.LTXV_PROMPTS:
            for r in ltx_keyframed.keyframe_rects(self.W, self.H, move):
                assert self._inside(r), move
                assert abs(r[2] / r[3] - aspect) < 0.01, move

    def test_directions(self):
        rects = lambda m: ltx_keyframed.keyframe_rects(self.W, self.H, m)
        a, b = rects("panright"); assert b[0] > a[0]
        a, b = rects("panleft"); assert b[0] < a[0]
        a, b = rects("panup"); assert b[1] < a[1]
        a, b = rects("pandown"); assert b[1] > a[1]
        a, b = rects("zoomin"); assert b[2] < a[2]
        a, b = rects("zoomout"); assert b[2] > a[2]
        a, b = rects("closein"); assert b[2] < a[2] < rects("zoomin")[1][2]
        a, b = rects("walkfwd"); assert b[2] < rects("closein")[1][2] < a[2]
        assert rects("walkfwdleft")[1][0] < b[0] < rects("walkfwdright")[1][0]

    def test_a_fixed_second_shot_follows_the_chosen_move(self, monkeypatch):
        monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT", "closein")
        assert ltx_keyframed.shot_list("panright") == ["panright", "closein"]
        monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT", None)
        assert ltx_keyframed.shot_list("panright") == ["panright"]

    def test_random_second_shot_is_repeatable_varied_and_never_the_same_way(self, monkeypatch):
        monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT", "random")
        monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT_MOVES", (
            "closein", "closeout", "closepanleft", "closepanright", "closepanup", "closepandown"))
        assert ltx_keyframed.second_shot("panright", "photo-a") == ltx_keyframed.second_shot("panright", "photo-a")
        picks = {ltx_keyframed.second_shot("panright", f"photo-{i}") for i in range(60)}
        assert len(picks) >= 4 and "closepanright" not in picks
        assert picks <= set(tuning.ATTRACTION_SECOND_SHOT_MOVES)
        assert "closein" not in {ltx_keyframed.second_shot("zoomin", f"p{i}") for i in range(60)}

    def test_close_moves_go_their_way(self):
        rects = lambda m: ltx_keyframed.keyframe_rects(self.W, self.H, m)
        a, b = rects("closeout"); assert b[2] > a[2]
        a, b = rects("closepanright"); assert b[0] > a[0] and b[2] == a[2]
        a, b = rects("closepanleft"); assert b[0] < a[0]
        a, b = rects("closepanup"); assert b[1] < a[1]
        a, b = rects("closepandown"); assert b[1] > a[1]


class TestTwoShots:
    def _clip(self, path, seconds):
        import subprocess

        from services.tts.ttsengine import FFmpegManager

        subprocess.run([FFmpegManager.resolve_ffmpeg_bin(), "-y", "-loglevel", "error", "-f", "lavfi", "-i",
                        f"testsrc2=size=960x544:rate=24:duration={seconds}", "-pix_fmt", "yuv420p", str(path)],
                       check=True)
        return str(path)

    def test_crossfade_overlaps_the_shots(self, tmp_path):
        from services.tts.ttsengine import FFmpegManager

        out = ltx_keyframed.crossfade([self._clip(tmp_path / "a.mp4", 4), self._clip(tmp_path / "b.mp4", 4)],
                                      str(tmp_path / "o.mp4"))
        assert abs(FFmpegManager.get_media_duration(out) - (8 - tuning.LTXV_CROSSFADE_SECONDS)) < 0.1

    def test_a_failed_second_shot_keeps_the_first(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ltx_keyframed, "ensure_files", lambda: None)
        monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT", "closein")
        photo = tmp_path / "p.png"
        photo.write_bytes(b"photo")
        made = []

        def render(photo, move, out, work, prompt=None):
            made.append(move)
            if move == "closein":
                raise RuntimeError("OOM")
            return self._clip(out, 4)

        monkeypatch.setattr(ltx_keyframed, "render_shot", render)
        out = ltx_keyframed.generate_ltx_move(str(photo), str(tmp_path / "o.mp4"), "zoom-in")
        from services.tts.ttsengine import FFmpegManager

        assert made == ["zoomin", "closein"]
        assert abs(FFmpegManager.get_media_duration(out) - 4) < 0.1

    def test_free_walk_has_no_pinned_last_frame(self):
        graph = ltx_keyframed.sample_graph("a.png", None, "p", 1, "x")
        assert not {"end", "guide", "crop"} & graph.keys()
        assert graph["cond"]["inputs"]["positive"] == ["i2v", 0]
        assert graph["lat"]["inputs"]["samples"] == ["sample", 0]
        assert "guide" in ltx_keyframed.sample_graph("a.png", "b.png", "p", 1, "x")

    def test_second_shot_pushes_in_with_the_camera_prompt_by_default(self):
        assert ltx_keyframed.prompt_for("closein", "abc", second=True) == \
            tuning.LTXV_PROMPTS["closein"].format(place="the scene")
        assert not set(tuning.ATTRACTION_SECOND_SHOT_MOVES) & set(tuning.LTXV_FREE_MOVES)

    def test_walk_in_is_rendered_as_a_pinned_walk(self, monkeypatch):
        assert ltx_keyframed.pinned_preset("walkin") == "walkfwd"
        assert ltx_keyframed.pinned_preset("panright") == "panright"
        monkeypatch.setattr(tuning, "LTXV_FREE_MOVE_FALLBACK", None)
        assert ltx_keyframed.pinned_preset("walkin") == "walkin"

    def test_pinned_walk_has_both_ends_pinned_and_goes_deeper_than_zoom(self):
        (fx, fy, fw, fh), (lx, ly, lw, lh) = ltx_keyframed.keyframe_rects(1920, 1080, "walkfwd")
        _, (_, _, zw, _) = ltx_keyframed.keyframe_rects(1920, 1080, "zoomin")
        assert lw < fw and lw < zw
        assert "walkfwd" not in tuning.LTXV_FREE_MOVES

    def test_pinned_walk_is_not_followed_by_another_push_in(self, monkeypatch):
        monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT", "random")
        for seed in "abcdefgh":
            assert ltx_keyframed.second_shot("walkfwd", seed) != "closein"

    def test_a_small_photo_takes_a_short_walk_with_zoom_crops(self, tmp_path):
        (tmp_path / "s").mkdir()
        (tmp_path / "b").mkdir()
        small = self._upscaled(tmp_path / "s", (800, 450))
        assert ltx_keyframed.sharp_enough_preset("walkfwd", small) == "walkshort"
        assert ltx_keyframed.keyframe_rects(1920, 1080, "walkshort") == ltx_keyframed.keyframe_rects(1920, 1080, "zoomin")
        assert ltx_keyframed.prompt_for("walkshort") == ltx_keyframed.prompt_for("walkfwd")
        assert ltx_keyframed.pinned_preset("zoomin") == "zoomin"
        big = self._upscaled(tmp_path / "b", (1920, 1080))
        assert ltx_keyframed.sharp_enough_preset("walkfwd", big) == "walkfwd"
        assert ltx_keyframed.sharp_enough_preset("panright", small) == "panright"

    def _upscaled(self, tmp_path, src_size, up_size=(1920, 1080)):
        from PIL import Image

        src, up_dir = tmp_path / "photo.jpg", tmp_path / "upscaled"
        up_dir.mkdir()
        up = up_dir / "photo.abc.png"
        Image.new("RGB", src_size).save(src)
        Image.new("RGB", up_size).save(up)
        (up_dir / "map.json").write_text(json.dumps({str(src): str(up)}), encoding="utf-8")
        return str(up)

    def test_a_small_original_photo_gets_no_second_shot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT", "closein")
        small = self._upscaled(tmp_path, (250, 187), (1920, 1436))
        assert ltx_keyframed.source_size(small) == (250, 187)
        assert ltx_keyframed.shot_list("panright", "s", small) == ["panright"]

    def test_a_large_enough_original_keeps_its_second_shot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT", "closein")
        big = self._upscaled(tmp_path, (1000, 500))
        assert ltx_keyframed.shot_list("panright", "s", big) == ["panright", "closein"]

    def test_a_photo_with_no_upscale_record_is_measured_itself(self, tmp_path):
        from PIL import Image

        path = tmp_path / "p.png"
        Image.new("RGB", (640, 480)).save(path)
        assert ltx_keyframed.source_size(str(path)) == (640, 480)

    def test_second_shot_walks_inside(self, monkeypatch):
        monkeypatch.setattr(tuning, "ATTRACTION_SECOND_SHOT_STYLE", "walk")
        walk = ltx_keyframed.prompt_for("closein", "abc", second=True)
        assert walk in [p.format(place="the place") for p in tuning.LTXV_WALK_PROMPTS["closein"]]
        assert walk == ltx_keyframed.prompt_for("closein", "abc", second=True)
        assert ltx_keyframed.prompt_for("closein", "abc") == tuning.LTXV_PROMPTS["closein"].format(place="the scene")


class TestGraph:
    def test_sample_graph_pins_the_last_frame_on_the_gguf_model(self):
        g = ltx_keyframed.sample_graph("a.png", "b.png", "p", 1, "x/y")
        types = {n["class_type"] for n in g.values()}
        assert "CheckpointLoaderSimple" not in types
        assert g["unet"]["class_type"] == "UnetLoaderGGUF"
        assert g["unet"]["inputs"]["unet_name"] == tuning.LTXV_FILES["unet"]["file"]
        assert g["guide"]["inputs"]["frame_idx"] == -1
        assert g["guide"]["inputs"]["strength"] == tuning.LTXV_GUIDE_STRENGTH
        assert g["i2v"]["inputs"]["length"] % 8 == 1
        assert (g["i2v"]["inputs"]["width"], g["i2v"]["inputs"]["height"]) == (tuning.LTXV_WIDTH, tuning.LTXV_HEIGHT)
        assert g["lat"]["class_type"] == "SaveLatent" and g["lat"]["inputs"]["samples"] == ["crop", 2]

    def test_decode_graph_saves_the_video_where_the_client_looks(self):
        g = ltx_keyframed.decode_graph("x.latent", "x/y")
        assert g["58"]["class_type"] == "SaveVideo" and g["lat"]["class_type"] == "LoadLatent"

    def test_pan_right_prompt_leads_with_the_move(self):
        assert ltx_keyframed.prompt_for("panright").startswith("A slow, calm gimbal shot pans smoothly to the right")


class TestRouting:
    def _gen(self, tmp_path):
        cfg = tmp_path / "job_config.json"
        cfg.write_text(json.dumps({"directory_path": str(tmp_path), "waypoints": []}), encoding="utf-8")
        return AttractionVideoGenerator(JobConfigManager(str(cfg)))

    def test_pan_right_uses_ltx(self, tmp_path, monkeypatch):
        calls = []
        monkeypatch.setattr(ltx_keyframed, "generate_ltx_move", lambda p, o, h: calls.append(h) or o)
        out = self._gen(tmp_path)._generate_single_clip("photo.png", "pan-right", 6.0, str(tmp_path / "o.mp4"))
        assert calls == ["pan-right"] and out.endswith("o.mp4")

    def test_ltx_failure_falls_back_to_the_3d_photo(self, tmp_path, monkeypatch):
        def boom(*a):
            raise RuntimeError("server down")

        monkeypatch.setattr(ltx_keyframed, "generate_ltx_move", boom)
        fallback = []
        monkeypatch.setattr(AttractionVideoGenerator, "_parallax_clip",
                            staticmethod(lambda i, s, d, p: fallback.append(p) or s))
        self._gen(tmp_path)._generate_single_clip("photo.png", "panright", 6.0, str(tmp_path / "o.mp4"))
        assert fallback == ["panright"]

    def test_no_preset_keeps_the_usual_generator(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ltx_keyframed, "generate_ltx_move", lambda *a: (_ for _ in ()).throw(AssertionError()))
        monkeypatch.setattr(tuning, "ATTRACTION_GENERATOR", "parallax")
        used = []
        monkeypatch.setattr(AttractionVideoGenerator, "_parallax_clip",
                            staticmethod(lambda i, s, d, p: used.append(p) or s))
        # No preset: the waypoint's label stands in as the prompt.
        self._gen(tmp_path)._generate_single_clip("photo.png", "西ノ庄駅", 6.0, str(tmp_path / "o.mp4"))
        assert used == ["西ノ庄駅"]

    def test_cache_key_changes_for_ltx_presets(self, tmp_path, monkeypatch):
        photo = _marked_photo(tmp_path / "p.png")
        with_ltx = img2vdo.AttractionVideoGenerator._clip_key(photo, "panright")
        monkeypatch.setattr(tuning, "ATTRACTION_LTX_PRESETS", ())
        assert img2vdo.AttractionVideoGenerator._clip_key(photo, "panright") != with_ltx
