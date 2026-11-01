"""An auto overview script is stored without undoing what the app saved while the model wrote it
(videopipeline/narration_step.ensure_overview_narration)."""

import json

from services.localization import overview_script, script_engine
from services.vdoprocessing.videopipeline import narration_step


def test_an_edit_saved_while_the_model_writes_is_kept(monkeypatch, tmp_path):
    config = tmp_path / "job_config.json"
    waypoints = [{"id": "a", "label": "Start", "lat": 34.0, "lng": 135.0}, {"id": "b", "label": "End", "lat": 34.01, "lng": 135.0}]
    config.write_text(json.dumps({"waypoints": waypoints, "settings": {}}), encoding="utf-8")

    def drafting(project, cache, generate):
        saved = json.loads(config.read_text(encoding="utf-8"))
        saved["waypoints"][1]["attractionNarration"] = "typed during the render"  # the app saves meanwhile
        config.write_text(json.dumps(saved), encoding="utf-8")
        return "{start}Here we go.{end}", []

    monkeypatch.setattr(script_engine, "script_generator", lambda settings: (None, "test"))
    monkeypatch.setattr(overview_script, "build_tour_script", drafting)

    assert narration_step.ensure_overview_narration(str(config))
    stored = json.loads(config.read_text(encoding="utf-8"))
    assert stored["waypoints"][1]["attractionNarration"] == "typed during the render"
    assert stored["overview_narration"] == "{start}Here we go.{end}" and stored["overview_narration_is_auto"] is True
