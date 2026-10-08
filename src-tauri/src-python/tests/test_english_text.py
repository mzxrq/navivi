"""English narration: sentences, captions and TTS chunks are cut where an English reader would cut them."""

import json

import pytest

from services import tuning
from services.localization.sentence_split import SENTENCE_END, split_sentences
from services.localization.subtitle import SubtitleBuilder, TextSegmenter, line_budget
from services.tts import kokoro_server
from services.tts.errors import TTSNotReady
from services.tts.ttsengine import KokoroTTSClient, make_tts_client, split_text_for_tts, tts_config_from_settings


def test_a_period_ends_a_sentence_but_an_abbreviation_or_decimal_point_does_not():
    text = "We reach Mt. Kabuto after 1.5 km. Then we go on to Nishinosho Sta. for the train. Done!"
    assert split_sentences(text) == [
        "We reach Mt. Kabuto after 1.5 km.",
        " Then we go on to Nishinosho Sta. for the train.",
        " Done!",
    ]


def test_splitting_loses_nothing_in_either_language():
    for text in ["猿坂峠です。次は甲山へ。", "Sarusaka Pass. Next, Mt. Kabuto.\nThe end.", ""]:
        assert "".join(SENTENCE_END.split(text)) == text


def test_japanese_sentences_are_cut_as_before():
    assert split_sentences("駅から出発します。猿坂峠へ向かいます！") == ["駅から出発します。", "猿坂峠へ向かいます！"]


def test_captions_do_not_break_at_abbreviations_or_decimals():
    assert TextSegmenter.split_clauses("Walk to Mt. Kabuto, 1.5 km away.") == ["Walk to Mt. Kabuto,", "1.5 km away."]
    assert TextSegmenter.split_clauses("駅から、出発します。") == ["駅から、", "出発します。"]


def test_an_english_caption_gets_a_wider_line_than_a_japanese_one():
    assert line_budget("Walk to the top of Mt. Kabuto", 20) == 40
    assert line_budget("甲山の山頂へ向かいます", 20) == 20
    assert line_budget("", 20) == 20


def test_a_long_english_clause_keeps_every_word_on_lines_as_wide_as_english_needs():
    clause = "Continue along the ridge until you reach the signpost for the pass."
    cues = SubtitleBuilder.build(clause, 6.0, [], max_chars_per_line=20)
    assert " ".join(cue.text for cue in cues) == clause
    assert all(len(line) <= 40 for cue in cues for line in cue.text.split("\n"))
    assert len(cues) < 4  # at 20 characters a line it would take 4


def test_tts_chunks_english_at_sentence_ends_and_joins_back_exactly():
    text = "First we walk to the station. Then we climb Mt. Kabuto for the view. At last we return."
    chunks = split_text_for_tts(text, 45)
    assert len(chunks) > 1
    assert "".join(chunks) == text
    assert not any(chunk.rstrip().endswith("Mt.") for chunk in chunks)


def test_a_kokoro_voice_id_says_which_language_it_speaks():
    assert [tuning.kokoro_language(v) for v in ("jf_tebukuro", "af_heart", "bf_emma", "am_michael", "")] == ["j", "a", "b", "a", "j"]
    assert [kokoro_server.language_of(v) for v in ("jm_kumo", "af_bella", "bf_emma", "zz_x")] == ["j", "a", "b", "j"]
    assert {"af_heart", "af_bella", "am_michael", "bf_emma"} <= set(tuning.KOKORO_VOICES)
    assert tuning.KOKORO_ENGLISH_VOICE in tuning.KOKORO_VOICES


def test_the_project_can_choose_an_english_kokoro_voice():
    config = tts_config_from_settings({"tts": {"engine": "kokoro", "kokoro_voice": "af_heart"}})
    assert (config.engine, config.voice) == ("kokoro", "af_heart")


def test_an_english_voice_stops_the_run_until_the_english_voices_are_set_up(monkeypatch, tmp_path):
    monkeypatch.setattr(KokoroTTSClient, "english_ready", classmethod(lambda cls: False))
    with pytest.raises(TTSNotReady, match="Add English voices"):
        make_tts_client({"tts": {"engine": "kokoro", "kokoro_voice": "af_heart"}}, tmp_path)
    make_tts_client({"tts": {"engine": "kokoro", "kokoro_voice": "jf_tebukuro"}}, tmp_path)  # Japanese is unaffected
    monkeypatch.setattr(KokoroTTSClient, "english_ready", classmethod(lambda cls: True))
    make_tts_client({"tts": {"engine": "kokoro", "kokoro_voice": "af_heart"}}, tmp_path)


def test_generate_audio_does_not_hide_a_voice_that_is_not_set_up(monkeypatch, tmp_path):
    from services.vdoprocessing.videopipeline import audio_step

    monkeypatch.setattr(KokoroTTSClient, "english_ready", classmethod(lambda cls: False))
    config = tmp_path / "job_config.json"
    config.write_text(
        json.dumps({"settings": {"tts": {"engine": "kokoro", "kokoro_voice": "af_heart"}}, "waypoints": [{"name": "A", "arrivingNarration": "Hello there."}]}),
        encoding="utf-8",
    )
    with pytest.raises(TTSNotReady):
        audio_step.generate_audio({}, str(config), str(tmp_path / "audio"))
