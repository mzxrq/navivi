from services.localization.cues import clean_text, strip_cues
from services.vdoprocessing.img2vdo import AttractionVideoGenerator
from services.vdoprocessing.photo_credit import credit_items


def test_a_next_cue_is_never_spoken_and_is_numbered():
    clean, cues = strip_cues("葛木水分神社です。{next}本殿は重要文化財です。{next}境内も広いです。")
    assert "{next}" not in clean and clean == clean_text("葛木水分神社です。本殿は重要文化財です。境内も広いです。")
    assert [c.tag for c in cues] == ["next1", "next2"]


def test_photos_take_the_time_between_next_cues():
    assert AttractionVideoGenerator.photo_shares(20.0, 3, [4.0, 12.0]) == [4.0, 8.0, 8.0]
    assert AttractionVideoGenerator.photo_shares(20.0, 3, [4.0]) is None  # not one cue per photo: equal split
    assert AttractionVideoGenerator.photo_shares(20.0, 2, [0.5]) is None  # a photo would flash by
    assert AttractionVideoGenerator.photo_shares(20.0, 1, []) is None


def test_credits_follow_the_cues():
    wp = {"images": ["a.jpg", "b.jpg"], "imageCredits": {"b.jpg": {"text": "Town office"}}}
    assert [(i["start"], i["end"]) for i in credit_items(wp, 20.0, cuts=[6.0])] == [(6.0, 20.0)]
    assert [(i["start"], i["end"]) for i in credit_items(wp, 20.0)] == [(10.0, 20.0)]

def test_the_cue_times_are_kept_beside_the_attraction_narration(tmp_path):
    from services.vdoprocessing.videopipeline.audio_step import _write_photo_cuts, read_photo_cuts

    audio = tmp_path / "04_attraction_01_A.wav"
    _write_photo_cuts(audio, "First part here. {next}Second part.", {"duration_seconds": 10.0, "pauses": []})
    cuts = read_photo_cuts(audio)
    assert len(cuts) == 1 and 4.0 < cuts[0] < 6.0  # about half way through the words
    _write_photo_cuts(audio, "No cue any more.", {"duration_seconds": 10.0, "pauses": []})
    assert read_photo_cuts(audio) == []