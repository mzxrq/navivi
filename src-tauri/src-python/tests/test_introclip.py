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
        ass_path = introclip._write_title_ass("My Trip", 5.0, tmp_path)
        assert ass_path.exists()
        content = ass_path.read_text(encoding="utf-8")
        assert "My Trip" in content
        assert "[Script Info]" in content
        assert "[V4 Styles]" in content
        assert "[Events]" in content
        assert r"\fad(" in content
        assert r"\fscx" in content

    def test_curly_braces_in_title_are_stripped(self, tmp_path):
        ass_path = introclip._write_title_ass("{evil}Trip", 5.0, tmp_path)
        content = ass_path.read_text(encoding="utf-8")
        # Only the override-tag braces should remain; the stripped title text
        # itself must not reintroduce a stray brace pair.
        dialogue_line = [l for l in content.splitlines() if l.startswith("Dialogue:")][0]
        assert "evilTrip" in dialogue_line

    def test_end_timestamp_matches_duration(self, tmp_path):
        ass_path = introclip._write_title_ass("Trip", 12.34, tmp_path)
        content = ass_path.read_text(encoding="utf-8")
        assert introclip._format_ass_timestamp(12.34) in content


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
