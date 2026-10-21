from services.vdoprocessing.videopipeline.render_step import purge_map_images_on_language_change


def _folder(tmp_path):
    folder = tmp_path / "assets" / "image" / "map"
    folder.mkdir(parents=True)
    (folder / "res_map_a.png").write_bytes(b"x")
    (folder / "overview_map.png").write_bytes(b"x")
    return folder


def test_images_with_no_note_are_fetched_again_once(tmp_path):
    folder = _folder(tmp_path)
    assert purge_map_images_on_language_change(tmp_path, "en")
    assert not list(folder.glob("*.png"))
    assert (folder / ".map_language").read_text() == "en"


def test_the_first_ever_render_has_nothing_to_delete(tmp_path):
    assert not purge_map_images_on_language_change(tmp_path, "en")


def test_a_new_language_deletes_the_map_images(tmp_path):
    folder = _folder(tmp_path)
    (folder / ".map_language").write_text("en")
    assert not purge_map_images_on_language_change(tmp_path, "en")
    assert (folder / "res_map_a.png").exists()
    assert purge_map_images_on_language_change(tmp_path, "ja")
    assert not list(folder.glob("*.png"))
    assert (folder / ".map_language").read_text() == "ja"
