"""A take whose voice misreads a spelled-out place name is heard back and retaken."""

import asyncio

import pytest

from services import tuning
from services.tts import name_check
from services.tts.ttsengine import KokoroTTSClient, make_tts_client
from tests.test_tts_cutoff import GOOD, _speech, _wav

OTHER = _wav(_speech(2.5))


def test_names_are_the_katakana_runs_with_their_plain_ending():
    assert name_check.expected_names("サルサカ峠へ、ミワ神社を経てゴールへ。") == [("サルサカ峠", "さるさかとうげ"), ("ミワ神社", "みわじんじゃ")]


def test_a_name_said_right_is_heard_even_written_in_kanji_or_voiced(monkeypatch):
    monkeypatch.setattr(name_check, "transcribe", lambda audio: "猿坂峠へ、いよいよ到着です。")
    assert name_check.misheard_names(b"", "サルサカ峠へ、いよいよ到着です。") == []
    monkeypatch.setattr(name_check, "transcribe", lambda audio: "さるざか峠へ。")
    assert name_check.misheard_names(b"", "サルサカ峠へ。") == []


def test_a_slurred_name_is_reported(monkeypatch):
    monkeypatch.setattr(name_check, "transcribe", lambda audio: "さらさか峠へ、いよいよ到着です。")
    assert name_check.misheard_names(b"", "サルサカ峠へ、いよいよ到着です。") == ["サルサカ峠"]


def test_nothing_is_checked_without_a_recogniser(monkeypatch):
    monkeypatch.setattr(name_check, "transcribe", lambda audio: "")
    assert name_check.misheard_names(b"", "サルサカ峠へ。") == []


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIVI_CACHE_DIR", str(tmp_path / "cache"))
    c = make_tts_client({"tts": {"engine": "kokoro"}}, tmp_path / "out")
    takes = iter([GOOD, OTHER, GOOD])
    c.calls = []

    async def call_api(self, text):
        c.calls.append(self.bypass_cache)
        return next(takes)

    monkeypatch.setattr(KokoroTTSClient, "call_api", call_api)
    return c


def test_a_misread_take_is_retaken_without_the_cache_until_the_name_is_heard(client, monkeypatch):
    monkeypatch.setattr(name_check, "transcribe", lambda audio: "猿坂峠へ。" if audio == OTHER else "さらさか峠へ。")
    assert asyncio.run(client._speak_chunk("サルサカ峠へ。")) == [OTHER]
    assert client.calls == [False, True]
    assert client.bypass_cache is False


def test_the_first_take_is_kept_when_no_retake_says_it_better(client, monkeypatch):
    monkeypatch.setattr(name_check, "transcribe", lambda audio: "さらさか峠へ。")
    assert asyncio.run(client._speak_chunk("サルサカ峠へ。")) == [GOOD]
    assert len(client.calls) == 1 + tuning.TTS_NAME_RETAKES
