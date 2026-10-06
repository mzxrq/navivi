"""Projects used to save marker_radius 10, which the engine floors to 16 (+3 px). The renderer defaults
must give that same pin size now that the frontend no longer writes the key."""

from services.mapfetcher.graphicengine import GraphicsEngine
from services.vdoprocessing.route2vdo import DEFAULT_MARKER_RADIUS


def test_default_pin_size_matches_what_a_saved_radius_of_10_rendered():
    saved = GraphicsEngine(marker_radius=10).marker_radius
    assert GraphicsEngine().marker_radius == saved == 19
    assert GraphicsEngine(marker_radius=DEFAULT_MARKER_RADIUS).marker_radius == saved
