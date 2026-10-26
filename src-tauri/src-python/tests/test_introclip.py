"""Unit tests for the pure/self-contained helpers in
services/vdoprocessing/introclip.py (geometry math, timestamp/ASS formatting,
random image selection). Ffmpeg/subprocess-driven paths (generate_intro_clip,
_crossfade_chain, _render_zoom_in) are integration-level and out of scope
here — they're exercised via the `intro` CLI mode instead.
"""

import random

import pytest

from services.vdoprocessing import introclip


class TestEaseInOut:
    def test_endpoints(self):
        assert introclip._ease_in_out(0.0) == pytest.approx(0.0, abs=1e-9)
        assert introclip._ease_in_out(1.0) == pytest.approx(1.0, abs=1e-9)

    def test_midpoint_is_half(self):
        assert introclip._ease_in_out(0.5) == pytest.approx(0.5, abs=1e-9)

    def test_monotonically_increasing(self):
        values = [introclip._ease_in_out(t / 10) for t in range(11)]
        assert values == sorted(values)


class TestCoverFit:
    def test_wide_source_crops_width(self):
        # Source is wider than the 16:9 target -> height is the limiting dim.
        fit_w, fit_h = introclip._cover_fit(2000, 500, out_aspect=16 / 9)
        assert fit_h == 500
        assert fit_w == int(500 * 16 / 9)

    def test_tall_source_crops_height(self):
        fit_w, fit_h = introclip._cover_fit(500, 2000, out_aspect=16 / 9)
        assert fit_w == 500
        assert fit_h == int(500 / (16 / 9))

    def test_matching_aspect_returns_full_source(self):
        fit_w, fit_h = introclip._cover_fit(1280, 720, out_aspect=1280 / 720)
        assert fit_w == 1280
        assert fit_h == 720


class TestCropRect:
    def test_centered_crop_within_bounds(self):
        x0, y0, x1, y1 = introclip._crop_rect(
            cx=50, cy=50, half_w=20, half_h=20, sw=100, sh=100
        )
        assert (x0, y0, x1, y1) == (30, 30, 70, 70)

    def test_crop_clamped_when_center_near_edge(self):
        # Center near the left edge — crop must not go negative.
        x0, y0, x1, y1 = introclip._crop_rect(
            cx=5, cy=50, half_w=20, half_h=20, sw=100, sh=100
        )
        assert x0 == 0
        assert x1 == 40

    def test_half_dims_larger_than_image_get_clamped(self):
        x0, y0, x1, y1 = introclip._crop_rect(
            cx=50, cy=50, half_w=1000, half_h=1000, sw=100, sh=100
        )
        assert x0 == 0
        assert y0 == 0
        assert x1 == 100
        assert y1 == 100


class TestFormatAssTimestamp:
    def test_zero(self):
        assert introclip._format_ass_timestamp(0.0) == "0:00:00.00"

    def test_sub_minute(self):
        assert introclip._format_ass_timestamp(5.25) == "0:00:05.25"

    def test_rolls_over_minutes_and_hours(self):
        assert introclip._format_ass_timestamp(3661.5) == "1:01:01.50"

    def test_negative_clamps_to_zero(self):
        assert introclip._format_ass_timestamp(-3.0) == "0:00:00.00"


class TestWriteTitleAss:
    def test_writes_file_with_expected_structure(self, tmp_path):
        ass_path = introclip._write_title_ass("My Trip", "", 5.0, tmp_path)
        assert ass_path.exists()
        content = ass_path.read_text(encoding="utf-8")
        assert "My Trip" in content
        assert "[Script Info]" in content
        assert "[V4 Styles]" in content
        assert "[Events]" in content
        assert r"\fad(" in content
        assert r"\fscx" in content

    def test_curly_braces_in_title_are_stripped(self, tmp_path):
        ass_path = introclip._write_title_ass("{evil}Trip", "", 5.0, tmp_path)
        content = ass_path.read_text(encoding="utf-8")
        # Only the override-tag braces should remain; the stripped title text
        # itself must not reintroduce a stray brace pair.
        dialogue_line = [l for l in content.splitlines() if l.startswith("Dialogue:")][0]
        assert "evilTrip" in dialogue_line

    def test_end_timestamp_matches_duration(self, tmp_path):
        ass_path = introclip._write_title_ass("Trip", "", 12.34, tmp_path)
        content = ass_path.read_text(encoding="utf-8")
        assert introclip._format_ass_timestamp(12.34) in content

    def test_subtitle_is_a_separate_staggered_event(self, tmp_path):
        ass_path = introclip._write_title_ass("Trip", "{x}Day 1", 5.0, tmp_path)
        lines = [l for l in ass_path.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue:")]
        assert len(lines) == 2
        title_line, sub_line = lines
        assert title_line.endswith("}Trip")
        assert sub_line.endswith("}xDay 1")
        assert r"\fs" + str(introclip.tuning.INTRO_SUBTITLE_FONT_SIZE) in sub_line
        assert r"\move(" in sub_line
        delay = introclip.tuning.INTRO_SUBTITLE_DELAY_SECONDS
        assert f",{introclip._format_ass_timestamp(delay)},{introclip._format_ass_timestamp(5.0 - delay)}," in sub_line

    def test_no_subtitle_writes_single_centered_event(self, tmp_path):
        ass_path = introclip._write_title_ass("Trip", "", 5.0, tmp_path)
        lines = [l for l in ass_path.read_text(encoding="utf-8").splitlines() if l.startswith("Dialogue:")]
        assert len(lines) == 1
        assert rf"\pos({introclip.tuning.INTRO_WIDTH // 2},{introclip.tuning.INTRO_HEIGHT // 2})" in lines[0]


class TestPickRandomImages:
    def test_no_images_returns_empty(self):
        assert introclip._pick_random_images([{"label": "a"}], count=3) == []

    def test_dedupes_shared_images_across_waypoints(self):
        waypoints = [
            {"popup_image": "same.jpg"},
            {"popup_image": "same.jpg"},
            {"popup_image": "different.jpg"},
        ]
        picked = introclip._pick_random_images(waypoints, count=10)
        assert sorted(picked) == ["different.jpg", "same.jpg"]

    def test_respects_requested_count(self):
        waypoints = [{"popup_image": f"img{i}.jpg"} for i in range(10)]
        picked = introclip._pick_random_images(waypoints, count=3)
        assert len(picked) == 3

    def test_handles_list_valued_popup_image(self):
        waypoints = [{"popup_image": ["a.jpg", "b.jpg"]}]
        picked = introclip._pick_random_images(waypoints, count=10)
        assert sorted(picked) == ["a.jpg", "b.jpg"]

    def test_skips_falsy_entries(self):
        waypoints = [{"popup_image": None}, {"popup_image": ""}, {"popup_image": "x.jpg"}]
        picked = introclip._pick_random_images(waypoints, count=10)
        assert picked == ["x.jpg"]

    def test_is_randomized_not_always_first_n(self, monkeypatch):
        calls = []

        def fake_sample(population, k):
            calls.append((list(population), k))
            return list(population)[:k]

        monkeypatch.setattr(random, "sample", fake_sample)
        waypoints = [{"popup_image": f"img{i}.jpg"} for i in range(5)]
        introclip._pick_random_images(waypoints, count=2)
        assert calls == [([f"img{i}.jpg" for i in range(5)], 2)]


class TestStyledIntro:
    def test_scene_starts_overlap_by_the_crossfade(self):
        assert introclip.scene_starts([4.0, 5.0, 3.0], 0.8) == [0.0, 3.2, 7.4]
        assert introclip.xfade_offsets([4.0, 5.0], 0.8) == [3.2]

    def test_busy_image_is_the_close_up(self):
        import numpy as np

        flat = np.full((270, 480, 3), 120, np.uint8)
        busy = (np.indices((270, 480)).sum(axis=0) % 8 < 4).astype(np.uint8)[..., None].repeat(3, 2) * 255
        d = {"flat.jpg": introclip.edge_density(flat), "busy.jpg": introclip.edge_density(busy)}
        assert introclip.pick_scenes(d) == ["busy.jpg", "flat.jpg"]
        assert introclip.pick_scenes({"only.mp4": 0.1}) == ["only.mp4", "only.mp4"]
        assert introclip.pick_scenes({}) == []

    def test_styled_length_matches_the_scene_table(self):
        assert introclip.styled_intro_seconds("cinematic") == pytest.approx(17.0 - 1.6)
        assert introclip.styled_intro_seconds("documentary") == pytest.approx(16.0 - 1.6)

    def test_title_scene_gets_a_third_distinct_source(self):
        d = {"a": 0.9, "b": 0.5, "c": 0.1}
        assert introclip.pick_scenes(d, 3) == ["a", "c", "b"]
        assert introclip.pick_scenes({"a": 0.9, "c": 0.1}, 3) == ["a", "c", "a"]

    def test_raw_footage_takes_one_raw_per_stop(self, tmp_path):
        for name in ("04_attraction_00_a.mp4", "raw_04_attraction_00_a_k1.mp4", "raw_04_attraction_00_a_k2.mp4",
                     "04_attraction_01_b.mp4"):
            (tmp_path / name).write_bytes(b"")
        clips = [str(tmp_path / "04_attraction_00_a.mp4"), str(tmp_path / "04_attraction_01_b.mp4")]
        assert introclip.raw_footage(clips) == [str(tmp_path / "raw_04_attraction_00_a_k1.mp4")]

    def test_transport_stops_are_not_scenery(self):
        assert introclip.is_transport_stop("x/04_attraction_00_寺田橋バス停.mp4", 13)
        assert introclip.is_transport_stop("x/04_attraction_12_玉手駅.mp4", 13)
        assert introclip.is_transport_stop("x/04_attraction_10_近鉄御所駅.mp4", 13)
        assert introclip.is_transport_stop("x/04_attraction_07_友ヶ島汽船.mp4", 19)
        assert not introclip.is_transport_stop("x/04_attraction_05_葛城一言主神社.mp4", 13)

    def test_scenes_stretch_to_the_voice(self):
        assert introclip.styled_intro_seconds("cinematic", 9.3) == pytest.approx(9.3)
        assert introclip.styled_intro_seconds("documentary", 22.0) == pytest.approx(22.0)
        assert [s["seconds"] for s in introclip.styled_scenes("cinematic")] == [5.5, 6.0, 5.5]

    def test_scene_cues_cut_the_intro(self):
        from services.localization.cues import cue_tags, clean_text
        from services.vdoprocessing.videopipeline.intro_step import scene_cuts

        text = "神話の時代から続く道へ。{scene}古い社を巡る。{scene}ようこそ。{start}これが全体のルートです。"
        assert cue_tags(text) == ["scene2", "scene3", "start"]
        assert "{" not in clean_text(text)
        cuts = scene_cuts({"scene2": 4.5, "scene3": 13.1, "start": 21.1})
        assert cuts == [5.0, 13.6]
        scenes = introclip.styled_scenes("documentary", 20.4, cuts)
        assert introclip.scene_starts([s["seconds"] for s in scenes], 0.8) == [0.0, 4.6, 13.2]
        assert sum(s["seconds"] for s in scenes) - 1.6 == pytest.approx(20.4)
        # A cut too close to the start falls back to stretching every scene alike.
        assert introclip.styled_scenes("documentary", 20.4, [0.5, 13.6])[0]["seconds"] > 5.0

    def test_scene_cues_are_placed_automatically(self):
        from services.localization.overview_cues import add_scene_cues

        script = "神話の時代から続く道へようこそ。美しい自然の中を巡る。昔に戻ったような気分。忙しい毎日を忘れて。この旅をお楽しみください。{start}これが全体のルートです。"
        tagged = add_scene_cues(script, [5.0, 5.5, 5.5])
        assert tagged.count("{scene}") == 2 and tagged.replace("{scene}", "") == script
        assert tagged.index("{scene}") > 0 and tagged.rindex("{scene}") < tagged.index("{start}")
        assert add_scene_cues("一文。{scene}二文。三文。{start}残り", [1, 1, 1]).count("{scene}") == 1  # the user's win
        assert add_scene_cues("一文だけ。{start}残り", [1, 1, 1]) == "一文だけ。{start}残り"

    def test_long_scenes_borrow_more_shots(self):
        lengths = {"a": 6.7, "b": 6.7, "c": 6.7, "d": 6.7, "photo.jpg": float("inf")}
        pool = ["b", "c", "d"]
        assert introclip.plan_shots(5.0, "a", pool, lengths, 0.8, 0) == ["a"] and pool == ["b", "c", "d"]
        assert introclip.plan_shots(9.4, "a", pool, lengths, 0.8, 1) == ["a", "d"] and pool == ["b", "c"]
        assert introclip.plan_shots(15.0, "a", pool, lengths, 0.8, 0) == ["a", "b", "c"]
        assert introclip.plan_shots(30.0, "photo.jpg", [], lengths, 0.8, 2) == ["photo.jpg"]

    def test_held_photo_clips_are_still(self):
        import numpy as np

        a = np.random.default_rng(0).integers(0, 255, (180, 320, 3), dtype=np.uint8)
        assert introclip.is_still(a, a.copy())
        assert not introclip.is_still(a, np.roll(a, 40, axis=1))
