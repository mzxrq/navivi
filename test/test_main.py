import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PYTHON_SOURCE_DIR = Path(__file__).resolve().parents[1] / "src-tauri" / "src-python"
if str(PYTHON_SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_SOURCE_DIR))

import main


class TestAllProcess(unittest.TestCase):
    def test_all_runs_every_stage_in_order_and_passes_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            config_path = project_dir / "job_config.json"
            config_path.write_text(
                json.dumps({"waypoints": [{"label": "Test Place"}]}),
                encoding="utf-8",
            )

            calls = []
            tts_result = {"clips": [{"audio_path": "audio.wav"}]}
            attraction_result = {"video_paths": ["attraction.mp4"]}
            subtitle_result = {"subtitle_paths": ["subtitle.srt"]}
            transition_result = {"video_paths": ["overview.mp4"]}
            concat_result = {"video_path": "03_concat.mp4"}

            def fake_tts(*args):
                calls.append(("tts", args))
                return tts_result

            def fake_attractions(*args):
                calls.append(("attractions", args))
                return attraction_result

            def fake_subtitles(*args):
                calls.append(("subtitles", args))
                return subtitle_result

            def fake_transition(*args):
                calls.append(("transition", args))
                return transition_result

            def fake_concat(*args):
                calls.append(("concat", args))
                return concat_result

            with patch.multiple(
                main,
                test_tts_all=fake_tts,
                test_attraction_videos=fake_attractions,
                test_subtitles=fake_subtitles,
                test_transition_editor=fake_transition,
                test_video_concat=fake_concat,
            ):
                result = main.test_all(str(config_path))

            self.assertEqual(
                [stage for stage, _ in calls],
                ["tts", "attractions", "subtitles", "transition", "concat"],
            )
            self.assertEqual(calls[0][1][0], str(config_path))
            self.assertEqual(calls[1][1][0], str(config_path))
            self.assertEqual(calls[2][1][0], str(config_path))
            self.assertEqual(calls[3][1][0], str(config_path))
            self.assertEqual(
                calls[4][1][2],
                ["attraction.mp4", "overview.mp4"],
            )
            self.assertEqual(result["tts"], tts_result)
            self.assertEqual(result["attractions"], attraction_result)
            self.assertEqual(result["subtitles"], subtitle_result)
            self.assertEqual(result["transition"], transition_result)
            self.assertEqual(result["concat"], concat_result)
            self.assertTrue(result["success"])

    def test_all_rejects_missing_config(self):
        with self.assertRaises(FileNotFoundError):
            main.test_all("does-not-exist/job_config.json")


if __name__ == "__main__":
    unittest.main()
