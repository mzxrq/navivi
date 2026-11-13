"""main.py answers an unknown mode with an error instead of rendering the overview."""

import json
import subprocess
import sys
from pathlib import Path

MAIN = Path(__file__).resolve().parents[1] / "main.py"


def test_an_unknown_mode_is_an_error_not_an_overview_render(tmp_path):
    cfg = tmp_path / "job_config.json"
    cfg.write_text(json.dumps({"waypoints": [], "settings": {}}), encoding="utf-8")
    run = subprocess.run([sys.executable, str(MAIN), str(cfg), "tts-al"], capture_output=True, text=True, encoding="utf-8", cwd=MAIN.parent, timeout=120)
    assert run.returncode == 1
    reply = json.loads(run.stdout)
    assert reply["success"] is False and "Unknown mode 'tts-al'" in reply["error"]
    assert not (tmp_path / "assets").exists()
