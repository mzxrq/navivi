import json

from services.vdoprocessing.videopipeline.narration_step import ensure_overview_narration


def _project(tmp_path, narration=""):
    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps({
        "overview_narration": narration,
        "waypoints": [{"id": "a"}, {"id": "b"}],
    }), encoding="utf-8")
    return cfg


def test_blanked_script_is_restored_without_llm(tmp_path):
    cfg = _project(tmp_path)
    (tmp_path / ".overview_narration.json").write_text(
        json.dumps({"source_ids": "a,b", "script": "{start}saved script"}), encoding="utf-8"
    )
    assert ensure_overview_narration(str(cfg)) is False
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["overview_narration"] == "{start}saved script"
    assert data["overview_narration_is_auto"] is True


def test_saved_script_for_other_waypoints_is_not_restored(tmp_path, monkeypatch):
    cfg = _project(tmp_path)
    (tmp_path / ".overview_narration.json").write_text(
        json.dumps({"source_ids": "a,c", "script": "old"}), encoding="utf-8"
    )
    import services.localization.overview_script as overview_script

    monkeypatch.setattr(overview_script, "build_tour_script", lambda *a, **k: ("{start}new", {}))
    monkeypatch.setattr(overview_script, "ollama_generate", lambda model: None)
    assert ensure_overview_narration(str(cfg)) is True
    assert json.loads(cfg.read_text(encoding="utf-8"))["overview_narration"] == "{start}new"
    saved = json.loads((tmp_path / ".navivi" / "overview_narration.json").read_text(encoding="utf-8"))
    assert saved == {"source_ids": "a,b", "script": "{start}new"}


def test_stopby_toggle_renumbers_the_saved_script(tmp_path, monkeypatch):
    cfg = tmp_path / "job_config.json"
    waypoints = [
        {"id": "a"}, {"id": "b"},
        {"id": "s", "isStopBy": True, "connectToRoute": True, "pauseAtWaypoint": True},
        {"id": "c"}, {"id": "z"},
    ]
    cfg.write_text(json.dumps({"overview_narration": "", "waypoints": waypoints}), encoding="utf-8")
    # saved before stop-bys were marked: "s" was only passed by then
    (tmp_path / ".overview_narration.json").write_text(
        json.dumps({"source_ids": "a,b,s,c,z", "script": "{start}old"}), encoding="utf-8"
    )
    import services.localization.overview_script as overview_script

    monkeypatch.setattr(overview_script, "build_tour_script", lambda *a, **k: ("{start}new", {}))
    monkeypatch.setattr(overview_script, "ollama_generate", lambda model: None)
    assert ensure_overview_narration(str(cfg)) is True
    saved = json.loads((tmp_path / ".navivi" / "overview_narration.json").read_text(encoding="utf-8"))
    assert saved["source_ids"] == "a,b,s+,c,z"


def _course_project(tmp_path, narration, is_auto):
    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps({
        "overview_narration": narration,
        "overview_narration_is_auto": is_auto,
        "settings": {"overview_style": "course", "overview_intro": "紹介文です。"},
        "waypoints": [
            {"id": "a", "label": "加太駅", "lat": 35.0, "lng": 139.0},
            {"id": "b", "label": "加太港", "lat": 35.0, "lng": 139.01},
            {"id": "c", "label": "加太駅 (Return)", "lat": 35.0, "lng": 139.0001},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return cfg


def test_a_script_the_user_wrote_is_kept_for_the_course_type(tmp_path, monkeypatch):
    import services.localization.overview_script as overview_script
    from services.localization.cues import clean_text
    from services.vdoprocessing.videopipeline.narration_step import add_overview_cues
    from services.vdoprocessing.videopipeline.audio_step import overview_tagged_script

    def never(*a, **k):
        raise AssertionError("a user's own script must never be rewritten")

    monkeypatch.setattr(overview_script, "build_tour_script", never)
    mine = "友ヶ島は四つの島からなっています。これが全体のルートです。加太駅から加太港へと向かいます。"
    for is_auto in (False, None):  # edited in the panel, or from before the flag existed
        cfg = _course_project(tmp_path, mine, is_auto)
        assert ensure_overview_narration(str(cfg)) is False
        add_overview_cues(str(cfg))
        project = json.loads(cfg.read_text(encoding="utf-8"))
        assert project["overview_narration"] == mine
        spoken = overview_tagged_script(project, tmp_path)
        assert clean_text(spoken) == mine  # tags only, never words
        assert "{start}これが全体のルートです。" in spoken


def test_an_automatic_script_is_rewritten_when_the_type_changes(tmp_path, monkeypatch):
    import services.localization.overview_script as overview_script

    monkeypatch.setattr(overview_script, "build_tour_script", lambda *a, **k: ("{start}course script", {}))
    monkeypatch.setattr(overview_script, "ollama_generate", lambda model: None)
    cfg = _course_project(tmp_path, "{start}walk script", True)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["overview_narration_source_ids"] = "a,b,c"  # written for the walk type
    cfg.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert ensure_overview_narration(str(cfg)) is True
    assert json.loads(cfg.read_text(encoding="utf-8"))["overview_narration"] == "{start}course script"
