"""Sanity checks on services/tuning.py's constants — guards against typos
(swapped min/max, out-of-range percentages) that would otherwise only
surface as a subtly wrong render.
"""

from services import tuning


class TestComfyUIConstants:
    def test_frame_bounds_are_ordered(self):
        assert tuning.COMFYUI_MIN_FRAMES < tuning.COMFYUI_MAX_FRAMES

    def test_camera_pan_prompts_cover_default(self):
        assert tuning.COMFYUI_DEFAULT_MOTION_PROMPT in tuning.COMFYUI_CAMERA_PAN_PROMPTS.values()

    def test_base_url_is_not_default_comfyui_port(self):
        # Deliberately not 8188 so it can't collide with a dev's own ComfyUI.
        assert "8189" in tuning.COMFYUI_BASE_URL
        assert "8188" not in tuning.COMFYUI_BASE_URL


class TestIntroConstants:
    def test_zoom_end_is_tighter_than_zoom_start(self):
        assert tuning.INTRO_ZOOM_END < tuning.INTRO_ZOOM_START

    def test_dim_factor_in_valid_range(self):
        assert 0.0 <= tuning.INTRO_IMAGE_DIM_FACTOR <= 1.0

    def test_label_scale_start_is_a_percentage_below_100(self):
        assert 0 < tuning.INTRO_LABEL_SCALE_START_PCT < 100

    def test_crossfade_shorter_than_per_image_duration(self):
        assert tuning.INTRO_CROSSFADE_SECONDS < tuning.INTRO_PER_IMAGE_SECONDS

    def test_total_intro_length_is_positive(self):
        total = (
            tuning.INTRO_IMAGE_COUNT * tuning.INTRO_PER_IMAGE_SECONDS
            - (tuning.INTRO_IMAGE_COUNT - 1) * tuning.INTRO_CROSSFADE_SECONDS
        )
        assert total > 0


class TestOutroConstants:
    def test_subtitle_template_has_count_placeholder(self):
        assert "{count}" in tuning.OUTRO_SUBTITLE_TEMPLATE

    def test_subtitle_template_formats_without_error(self):
        assert tuning.OUTRO_SUBTITLE_TEMPLATE.format(count=5) == "訪れた5か所"

    def test_grid_col_cap_is_positive(self):
        assert tuning.OUTRO_GRID_COLS_MAX > 0

    def test_badge_color_is_marker_color_reversed(self):
        assert tuning.OUTRO_BADGE_COLOR == tuple(reversed(tuning.DEFAULT_MARKER_COLOR))


class TestTTSConstants:
    def test_default_speed_within_allowed_bounds(self):
        assert tuning.TTS_MIN_SPEED <= tuning.TTS_SPEED <= tuning.TTS_MAX_SPEED
