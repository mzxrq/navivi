import os

from services.vdoprocessing.videopipeline import clip_cache


def test_clip_is_reused_until_an_input_or_file_changes(tmp_path):
    clip = tmp_path / "assets" / "video" / "00_intro.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"x")
    photo = tmp_path / "a.jpg"
    photo.write_bytes(b"1")

    key = clip_cache.fingerprint({"title": "Trip"}, [photo])
    assert not clip_cache.reusable(tmp_path, clip, key)
    clip_cache.remember(tmp_path, clip, key)
    assert clip_cache.reusable(tmp_path, clip, key)

    assert clip_cache.fingerprint({"title": "Other"}, [photo]) != key
    photo.write_bytes(b"22")
    os.utime(photo, (1, 1))
    assert clip_cache.fingerprint({"title": "Trip"}, [photo]) != key

    clip.unlink()
    assert not clip_cache.reusable(tmp_path, clip, key)
