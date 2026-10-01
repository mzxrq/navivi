from services import projectfiles as pf


def test_writers_use_the_navivi_folder(tmp_path):
    path = pf.meta_path(tmp_path, pf.ROUTE_CACHE)
    assert path == tmp_path / ".navivi" / "routecache.json"
    assert path.parent.is_dir()


def test_readers_fall_back_to_the_old_name_until_the_new_file_exists(tmp_path):
    legacy = tmp_path / ".narration_cues.json"
    legacy.write_text("{}", encoding="utf-8")
    assert pf.meta_file(tmp_path, pf.NARRATION_CUES) == legacy

    current = pf.meta_path(tmp_path, pf.NARRATION_CUES)
    current.write_text("{}", encoding="utf-8")
    assert pf.meta_file(tmp_path, pf.NARRATION_CUES) == current


def test_missing_file_resolves_to_the_new_place(tmp_path):
    assert pf.meta_file(tmp_path, pf.OVERVIEW_NARRATION) == tmp_path / ".navivi" / "overview_narration.json"


def test_tile_cache_is_shared_not_per_project(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVIVI_CACHE_DIR", str(tmp_path / "cache"))
    assert pf.tile_cache_dir() == tmp_path / "cache" / "tiles"
    monkeypatch.delenv("NAVIVI_CACHE_DIR")
    assert pf.tile_cache_dir().parts[-3:] == ("Navivi", "Cache", "tiles")
