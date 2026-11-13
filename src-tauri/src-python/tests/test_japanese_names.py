import pytest

from services.tts import japanese_names, kokoro_server


@pytest.fixture(autouse=True)
def empty_registry():
    japanese_names._readings.clear()
    yield
    japanese_names._readings.clear()


def test_an_english_line_keeps_its_text_and_remembers_the_kana_reading():
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary

    line = "Next, we visit Kuhonji."
    assert apply_pronunciation_dictionary(line, [{"word": "Kuhonji", "reading": "くほんじ"}]) == line
    assert japanese_names._readings == {"Kuhonji": "くほんじ"}


def test_mark_wraps_whole_words_longest_first_in_any_case():
    japanese_names.remember("Katsuragi", "かつらぎ")
    japanese_names.remember("Katsuragi Hitokotonushi Jinja", "かつらぎひとことぬしじんじゃ")
    japanese_names.remember("Kuhonji", "くほんじ")
    assert japanese_names.mark("katsuragi Hitokotonushi Jinja, Kuhonji's gate, Kuhonjiya, Katsuragi.") == (
        "[katsuragi Hitokotonushi Jinja](ja:かつらぎひとことぬしじんじゃ), [Kuhonji](ja:くほんじ)'s gate, Kuhonjiya, [Katsuragi](ja:かつらぎ)."
    )


def test_a_hyphen_next_to_a_name_becomes_a_space():
    japanese_names.remember("Meiji", "めいじ")
    japanese_names.remember("Kami", "かみ")
    japanese_names.remember("Gose-machi", "ごせまち")
    assert japanese_names.mark("A Meiji-era office, Hitokotonushi-no-Kami, Gose-machi.") == (
        "A [Meiji](ja:めいじ) era office, Hitokotonushi-no [Kami](ja:かみ), [Gose-machi](ja:ごせまち)."
    )


def test_a_reading_in_slashes_goes_to_the_fast_voice_as_sounds_and_leaves_the_line_alone_for_others():
    from services.vdoprocessing.videopipeline.audio_step import apply_pronunciation_dictionary

    entries = [{"word": "Kuhonji", "reading": "/kuhoːnʤi/"}, {"word": "Meiji", "reading": "/meːʤi/"}]
    for line in ("A Meiji-era hall at Kuhonji.", "九品寺へ"):
        assert apply_pronunciation_dictionary(line, entries) == line
    assert japanese_names.mark("A Meiji-era hall at Kuhonji.") == "A [Meiji](/meːʤi/) era hall at [Kuhonji](/kuhoːnʤi/)."


def test_nothing_remembered_leaves_the_line_alone():
    assert japanese_names.mark("Next, we visit [Kuhonji].") == "Next, we visit [Kuhonji]."


def test_a_japanese_voice_gets_the_reading_instead_of_the_mark():
    assert kokoro_server.with_japanese_names("[Kuhonji](ja:くほんじ)へ", "jf_alpha") == "くほんじへ"
