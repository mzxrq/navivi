import asyncio
import wave

from services.tts import ttsengine
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


def test_sentences_stay_whole_and_group_until_min_chars():
    assert split_text_for_tts("あいうえお。かきくけこ。さしすせそ。", 12) == ["あいうえお。", "かきくけこ。", "さしすせそ。"]
    assert split_text_for_tts("あいうえお。かきくけこ。さしすせそ。たちつてと。", 12, 10) == ["あいうえお。かきくけこ。", "さしすせそ。たちつてと。"]


def test_editing_one_sentence_changes_only_its_own_chunk():
    sentences = [f"{i}番目の文はこのくらいの長さで続いていきます。" for i in range(8)]
    before = split_text_for_tts("".join(sentences), 60, 20)
    sentences[2] = "短くした文。"
    after = split_text_for_tts("".join(sentences), 60, 20)
    assert len(set(before) - set(after)) <= 2  # the edited sentence's chunk, at most its neighbour too


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
    monkeypatch.setattr(ttsengine, "cut_off_ratio", lambda wav: 0.0)  # the flat fake never fades out
    text = "これは長い文章です。" * 12  # 12 identical 10-char sentences, 120 characters
    out = asyncio.run(client.generate_speech(text, "long.wav"))
    # Sentences grouped until a chunk has TTS_MIN_CHUNK_CHARS (20): 2 per request, 6 requests of a fixed 1.0 s
    # fake clip each, joined with 5 random gaps.
    assert len(sent) == 6 and "".join(sent) == text
    from services import tuning
    min_total = 6.0 + 5 * tuning.TTS_SENTENCE_GAP_MIN_SECONDS
    max_total = 6.0 + 5 * tuning.TTS_SENTENCE_GAP_MAX_SECONDS
    with wave.open(out, "rb") as wf:
        duration = wf.getnframes() / wf.getframerate()
        assert min_total - 0.05 <= duration <= max_total + 0.05
    assert not list(tmp_path.glob("*.part*.wav"))
    assert not list(tmp_path.glob("*.gap*.wav"))


def test_an_unchanged_overview_voice_is_retaken_without_the_cache_only_when_asked(tmp_path):
    from services.vdoprocessing.videopipeline import audio_step

    class Client:
        bypass_cache = False
        seen = []

        async def generate_speech(self, text, output_filename):
            self.seen.append(self.bypass_cache)
            path = tmp_path / output_filename
            path.write_bytes(_wav_bytes(tmp_path / "src.wav", 1.0))
            return str(path)

    class Processor:
        def analyze_pauses(self, path):
            return {"duration_seconds": 1.0, "pauses": []}

    client = Client()
    voice = lambda retake: asyncio.run(audio_step._voice_piece(  # noqa: E731
        "{start}全体のルートです。", "00_overview_narration.wav", {}, client, Processor(), tmp_path, False, [], retake=retake))
    voice(False)  # no file yet: made, with the cache
    voice(False)  # unchanged: reused
    voice(True)   # unchanged but a retake: made again, past the cache
    assert client.seen == [False, True] and client.bypass_cache is False


def test_kept_sentences_are_reused_and_only_edited_or_picked_ones_spoken_again(tmp_path, monkeypatch):
    from services.tts import voice_pieces

    client = IrodoriTTSClient(output_dir=tmp_path)
    sent, made = [], []

    async def fake_call(text):
        sent.append(text)
        made.append(text)
        return _wav_bytes(tmp_path / "src.wav", 1.0 + 0.01 * len(made))  # every take differs

    monkeypatch.setattr(client, "call_api", fake_call)
    monkeypatch.setattr(ttsengine, "cut_off_ratio", lambda wav: 0.0)
    client.pieces_dir, client.pieces_voice = tmp_path / "pieces", {"voice": "a"}
    first = ["一つ目の文は少し長めに書いてここで終わります。", "二つ目の文も少し長めに書いてここで終わります。", "三つ目の文も少し長めに書いてここで終わります。"]

    asyncio.run(client.generate_speech("".join(first), "n.wav"))
    assert len(sent) == 3
    assert [p["text"] for p in voice_pieces.listing(client.pieces_dir)] == first

    sent.clear()
    edited = [first[0], "二つ目は書き直して別の長い文になりました。", first[2]]
    asyncio.run(client.generate_speech("".join(edited), "n.wav"))
    assert sent == [edited[1]]  # only the edited sentence
    assert len(list(client.pieces_dir.glob("*.wav"))) == 3  # the old take of sentence 2 is gone

    sent.clear()
    client.redo_texts = frozenset(voice_pieces.texts(client.pieces_dir, [2]))
    asyncio.run(client.generate_speech("".join(edited), "n.wav"))
    assert sent == [edited[2]]  # only the picked one

    sent.clear()
    client.redo_texts, client.pieces_voice = frozenset(), {"voice": "b"}
    asyncio.run(client.generate_speech("".join(edited), "n.wav"))
    assert len(sent) == 3  # another voice: all of it
