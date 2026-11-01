"""{photo:X} cues in the opening (videopipeline/intro_step.photo_cuts)."""

from services.vdoprocessing.videopipeline.intro_step import photo_cuts


def test_a_stop_saved_without_photos_is_skipped_not_a_crash():
    waypoints = [
        {"label": "Kada Station", "popup_image": []},  # how the app saves a stop with no photo
        {"label": "Kada Shrine", "popup_image": ["a.jpg", "b.jpg"]},
        {"label": "Pier", "popup_image": "pier.jpg"},
    ]
    cuts = photo_cuts({"photo1:Kada Station": 1.0, "photo2:Shrine": 2.0, "photo3:Pier": 3.0}, waypoints)
    assert [p for _, p in cuts] == ["a.jpg", "pier.jpg"]
