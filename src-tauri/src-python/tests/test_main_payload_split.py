"""main.py: only a stage call ("<job_config.json>", "tts 3 --force") is split into arguments; named commands keep
their payload whole (a font family or a path with a space used to be cut into pieces)."""

from main import split_mode_payload


def test_a_stage_payload_is_split():
    assert split_mode_payload(["main.py", "C:/p/job_config.json", "tts 3 --force"]) == [
        "main.py", "C:/p/job_config.json", "tts", "3", "--force",
    ]


def test_a_single_word_mode_is_untouched():
    argv = ["main.py", "C:/p/job_config.json", "tts-all"]
    assert split_mode_payload(argv) == argv


def test_named_commands_keep_a_payload_with_spaces_whole():
    for command, payload in [
        ("install_google_font", "Noto Sans JP"),
        ("extract_words", "今日は 晴れ です"),
        ("read_document", "C:/My Docs/a b.pdf"),
        ("import_gps_track", '{"path": "C:/My Docs/a.gpx", "radius_m": 30}'),
        ("tts_voice_add", '{"name": "my voice"}'),
        ("convert_images", '{"paths": ["a b.heic"]}'),
        ("full_pipeline", "C:/My Projects/job_config.json"),
    ]:
        argv = ["main.py", command, payload]
        assert split_mode_payload(argv) == argv


def test_a_json_payload_after_a_job_config_is_not_split():
    argv = ["main.py", "C:/p/job_config.json", '{"a": 1}']
    assert split_mode_payload(argv) == argv
