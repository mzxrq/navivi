import wave

import numpy as np

from services.tts.artifacts import find_stray_bursts, remove_stray_bursts

SR = 24000


def _tone(seconds, level=0.3):
    t = np.arange(int(SR * seconds)) / SR
    return level * np.sin(2 * np.pi * 220 * t)


def _silence(seconds):
    return np.zeros(int(SR * seconds))


def _write(path, signal):
    pcm = (np.clip(signal, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def _read(path):
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def test_burst_alone_in_a_pause_is_removed_and_speech_is_untouched(tmp_path):
    speech_a, speech_b = _tone(0.8), _tone(0.9)
    signal = np.concatenate([speech_a, _silence(0.4), _tone(0.05, 0.4), _silence(0.5), speech_b])
    path = tmp_path / "a.wav"
    _write(path, signal)

    assert remove_stray_bursts(str(path)) == [1.2]
    out = _read(path)
    assert len(out) == len(signal)
    burst = slice(int(SR * 1.2), int(SR * 1.25))
    assert np.abs(out[burst]).max() < 0.01
    assert np.allclose(out[: int(SR * 0.8)], signal[: int(SR * 0.8)], atol=1e-3)
    assert np.allclose(out[-int(SR * 0.9):], signal[-int(SR * 0.9):], atol=1e-3)


def test_short_sound_between_close_words_is_kept(tmp_path):
    signal = np.concatenate([_tone(0.5), _silence(0.05), _tone(0.06), _silence(0.05), _tone(0.5)])
    path = tmp_path / "b.wav"
    _write(path, signal)
    assert remove_stray_bursts(str(path)) == []


def test_a_clean_file_is_not_rewritten(tmp_path):
    path = tmp_path / "c.wav"
    _write(path, np.concatenate([_tone(0.6), _silence(0.4), _tone(0.7)]))
    before = path.read_bytes()
    assert remove_stray_bursts(str(path)) == []
    assert path.read_bytes() == before


def test_burst_at_the_very_start_counts_as_stray():
    signal = np.concatenate([_tone(0.05, 0.4), _silence(0.4), _tone(0.8)])
    assert len(find_stray_bursts(signal, SR)) == 1


def test_non_wav_input_is_ignored(tmp_path):
    path = tmp_path / "d.wav"
    path.write_bytes(b"not a wav")
    assert remove_stray_bursts(str(path)) == []
