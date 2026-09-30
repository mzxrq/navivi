"""_resolve_attraction_audio (services/cli/attraction_commands.py): the
single-waypoint `attraction <i>` CLI test must size the clip against the
waypoint's own ATTRACTION audio, never the combined route+attraction one -
the real pipeline (attraction_step.render_attraction_videos) always sizes
against attraction_audio_durations, and with route-only legs on
(audio_step.set_route_only_legs) the combined file is shorter (arrival text
only), which used to size the CLI's clip too short."""

from pathlib import Path

from services.cli.attraction_commands import _resolve_attraction_audio
from services.vdoprocessing.videopipeline.helpers import (
    attraction_audio_filename,
    waypoint_audio_filename,
)


def _write_wav(path: Path, seconds: float):
    import wave

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * int(16000 * seconds))


class TestResolveAttractionAudio:
    def test_uses_the_attraction_only_audio_not_the_combined_one(self, tmp_path):
        config_path = tmp_path / "job_config.json"
        audio_dir = tmp_path / "assets" / "audio"
        # combined route+attraction file: short, route-only text
        _write_wav(audio_dir / waypoint_audio_filename(1, "石標"), 3.0)
        # the waypoint's own attraction-only audio: the real duration to size against
        _write_wav(audio_dir / attraction_audio_filename(1, "石標"), 12.0)

        info = _resolve_attraction_audio(config_path, 1, "石標")
        assert round(info["duration_seconds"]) == 12
        assert info["audio_path"].endswith(attraction_audio_filename(1, "石標"))

    def test_no_attraction_audio_yet_is_reported_as_no_duration(self, tmp_path):
        config_path = tmp_path / "job_config.json"
        info = _resolve_attraction_audio(config_path, 0, "石標")
        assert info == {"audio_path": None, "duration_seconds": 0.0}
