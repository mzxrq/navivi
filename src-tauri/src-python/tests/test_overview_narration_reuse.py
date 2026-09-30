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
    saved = json.loads((tmp_path / ".overview_narration.json").read_text(encoding="utf-8"))
    assert saved == {"source_ids": "a,b", "script": "{start}new"}
