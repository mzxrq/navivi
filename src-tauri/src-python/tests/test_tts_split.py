import asyncio
import wave

from services.tts.ttsengine import IrodoriTTSClient, split_text_for_tts


def test_short_text_is_one_chunk():
    assert split_text_for_tts("短い文です。", 60) == ["短い文です。"]
    assert split_text_for_tts("", 60) == []


def test_chunks_join_back_to_the_text_and_respect_the_limit():
    text = (
        "加太から友ヶ島へ、修験の道をめぐる旅が始まります。出発は、南海電鉄加太線の加太駅です。"
        "まずは加太の町を歩きながら、石標、常行寺、加太春日神社、称念寺と、ゆかりの場所を順にたどっていきます。"
        "町のあちこちに、古くから祈りの気配が息づいています。"
    )
    chunks = split_text_for_tts(text, 60)
    assert "".join(chunks) == text
    assert all(0 < len(c) <= 60 for c in chunks)
    assert len(chunks) >= 3


def test_sentences_stay_whole_when_they_fit():
    chunks = split_text_for_tts("あいうえお。かきくけこ。さしすせそ。", 12)
    assert chunks == ["あいうえお。かきくけこ。", "さしすせそ。"]


def test_a_sentence_without_commas_is_cut_at_the_limit():
    chunks = split_text_for_tts("あ" * 130, 60)
    assert [len(c) for c in chunks] == [60, 60, 10]


def _wav_bytes(path, seconds, rate=8000):
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"\x10\x00" * int(rate * seconds))
    return path.read_bytes()


def test_long_text_is_spoken_in_chunks_and_joined(tmp_path, monkeypatch):
    client = IrodoriTTSClient(output_dir=tmp_path)
    sent = []

    async def fake_call(text):
        sent.append(text)
        return _wav_bytes(tmp_path / "src.wav", 1.0)

    monkeypatch.setattr(client, "call_api", fake_call)
    text = "これは長い文章です。" * 12  # 12 identical 10-char sentences, 120 characters
    out = asyncio.run(client.generate_speech(text, "long.wav"))
    # Sentences packed up to TTS_MAX_CHUNK_CHARS per request (not one
    # request per sentence - see split_text_for_tts): 6 sentences (60
    # chars) fit exactly per chunk, so 12 sentences make 2 chunks/requests
    # - and fake_call returns a fixed 1.0s clip per REQUEST regardless of
    # how much text it was given, so 2 requests = 2.0s of "speech". A short
    # randomized silence is inserted between chunks (not between every
    # sentence within one), so the joined duration is that 2.0s plus 1 gap
    # somewhere in tuning's [MIN, MAX] range.
    assert len(sent) == 2 and "".join(sent) == text
    from services import tuning
    min_total = 2.0 + 1 * tuning.TTS_SENTENCE_GAP_MIN_SECONDS
    max_total = 2.0 + 1 * tuning.TTS_SENTENCE_GAP_MAX_SECONDS
    with wave.open(out, "rb") as wf:
        duration = wf.getnframes() / wf.getframerate()
        assert min_total - 0.05 <= duration <= max_total + 0.05
    assert not list(tmp_path.glob("*.part*.wav"))
    assert not list(tmp_path.glob("*.gap*.wav"))
