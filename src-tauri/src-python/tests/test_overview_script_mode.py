"""The overview-script / overview_length modes the overview panel calls: their JSON contract,
and how the pipeline treats a hand-written overview narration."""

import json

from services.cli.script_commands import overview_length, test_overview_script as draft_overview
from services.vdoprocessing.videopipeline.narration_step import ensure_overview_narration

REPLY_KEYS = {
    "script", "draft_path", "model", "source_ids", "spoken_chars", "chars_per_second", "target_seconds",
    "estimated_seconds", "within_60_90s", "min_seconds", "max_seconds", "stopped_at", "pieces",
}


def _route(stops=3):
    wps = [{"id": "w0", "label": "起点", "lat": 35.0, "lng": 139.0, "routeMode": "walking"}]
    for n in range(1, stops + 1):
        wps.append({
            "id": f"w{n}", "label": f"場所{n}", "lat": 35.0, "lng": 139.0 + 0.004 * n, "routeMode": "walking",
            "attractionNarration": "ここは古い町並みが残る場所です。" * n,
        })
    wps.append({"id": "wz", "label": "終点", "lat": 35.0, "lng": 139.0 + 0.004 * (stops + 1), "routeMode": "walking"})
    return wps


def _config(tmp_path, **extra):
    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps({
        "waypoints": _route(),
        "settings": {"overview_describe_stops": True},
        **extra,
    }, ensure_ascii=False), encoding="utf-8")
    return cfg


def test_the_draft_reply_has_the_fields_the_panel_reads(tmp_path):
    cfg = _config(tmp_path)
    reply = draft_overview(str(cfg), use_llm=False)
    assert reply["success"] is True
    assert REPLY_KEYS <= set(reply)
    assert reply["model"] is None
    assert reply["script"].strip() and "{1}" in reply["script"]
    assert reply["source_ids"] == "w0,w1,w2,w3,wz"
    assert reply["stopped_at"] == [1, 2, 3]
    assert reply["min_seconds"] == 60.0 and reply["max_seconds"] == 120.0
    assert reply["estimated_seconds"] > 0 and reply["chars_per_second"] > 0
    assert isinstance(reply["within_60_90s"], bool)
    assert {"kind", "used", "budget_chars", "text"} <= set(reply["pieces"][0])
    assert (tmp_path / "overview_script_draft.txt").read_text(encoding="utf-8") == reply["script"]


def test_the_draft_never_touches_the_narration_in_the_config(tmp_path):
    cfg = _config(tmp_path, overview_narration="自分で書いた案内です。", overview_narration_is_auto=False)
    before = cfg.read_text(encoding="utf-8")
    draft_overview(str(cfg), use_llm=False)
    assert cfg.read_text(encoding="utf-8") == before


def test_the_length_of_a_typed_script_uses_the_projects_voice_speed(tmp_path):
    cfg = _config(tmp_path)
    reply = overview_length(str(cfg), "{start}" + "あ" * 100 + "{1}")
    assert reply["success"] is True
    assert reply["spoken_chars"] == 100  # cue tags are never spoken
    assert reply["estimated_seconds"] == round(100 / reply["chars_per_second"], 1)
    assert reply["within_60_90s"] is False  # about 16 s
    # the same script at a faster voice is shorter
    cfg.write_text(json.dumps({"waypoints": _route(), "settings": {"overview_chars_per_second": 10}}), encoding="utf-8")
    assert overview_length(str(cfg), "あ" * 100)["estimated_seconds"] == 10.0
    assert overview_length(str(cfg), "あ" * 1000)["within_60_90s"] is True


def test_the_length_of_nothing_is_zero(tmp_path):
    reply = overview_length(str(_config(tmp_path)), "")
    assert reply["spoken_chars"] == 0 and reply["estimated_seconds"] == 0.0


def test_a_hand_written_script_is_kept_when_the_stops_change(tmp_path, monkeypatch):
    cfg = _config(tmp_path, overview_narration="自分の案内文です。", overview_narration_is_auto=False,
                  overview_narration_source_ids="old")
    import services.localization.overview_script as overview_script

    def boom(*args, **kwargs):
        raise AssertionError("must not write over a hand-written overview")

    monkeypatch.setattr(overview_script, "build_tour_script", boom)
    assert ensure_overview_narration(str(cfg)) is False
    assert json.loads(cfg.read_text(encoding="utf-8"))["overview_narration"] == "自分の案内文です。"


def test_a_stale_auto_script_is_replaced_by_the_saved_one_for_the_current_stops(tmp_path):
    # the editor saved the auto script it had loaded, after a render had already written a newer one
    cfg = _config(tmp_path, overview_narration="{start}古い案内", overview_narration_is_auto=True,
                  overview_narration_source_ids="w0,w1,wz")
    saved = tmp_path / ".navivi"
    saved.mkdir()
    (saved / "overview_narration.json").write_text(
        json.dumps({"source_ids": "w0,w1,w2,w3,wz", "script": "{start}新しい案内"}, ensure_ascii=False), encoding="utf-8"
    )
    assert ensure_overview_narration(str(cfg)) is False
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["overview_narration"] == "{start}新しい案内"
    assert data["overview_narration_is_auto"] is True


def test_a_fresh_auto_script_is_left_alone(tmp_path, monkeypatch):
    cfg = _config(tmp_path, overview_narration="{start}今の案内", overview_narration_is_auto=True,
                  overview_narration_source_ids="w0,w1,w2,w3,wz")
    import services.localization.overview_script as overview_script

    monkeypatch.setattr(overview_script, "build_tour_script", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no rewrite")))
    assert ensure_overview_narration(str(cfg)) is False
    assert json.loads(cfg.read_text(encoding="utf-8"))["overview_narration"] == "{start}今の案内"
