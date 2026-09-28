import subprocess

from services.tts.ttsengine import FFmpegManager
from services.vdoprocessing.vdoexporter import VideoExporter


def _ffmpeg():
    return str(VideoExporter.resolve_ffmpeg())


def _make(tmp_path, video_seconds, audio_seconds):
    video, audio = tmp_path / "v.mp4", tmp_path / "a.wav"
    subprocess.run([_ffmpeg(), "-y", "-f", "lavfi", "-i", f"color=c=blue:s=160x90:r=30:d={video_seconds}",
                    "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True)
    subprocess.run([_ffmpeg(), "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={audio_seconds}",
                    str(audio)], check=True, capture_output=True)
    return video, audio


def _video_len(path):
    out = subprocess.run([_ffmpeg(), "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "null", "-"],
                         capture_output=True, encoding="utf-8", errors="replace").stderr
    line = [ln for ln in out.splitlines() if "time=" in ln][-1]
    h, m, s = line.split("time=")[1].split()[0].split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def test_video_is_held_until_the_audio_ends(tmp_path):
    video, audio = _make(tmp_path, 2.0, 5.0)
    out = VideoExporter._mux_track_for_concat(_ffmpeg(), video, str(audio), tmp_path, 0, audio_offset=1.0)
    assert _video_len(out) >= 5.0 + 1.0 - 0.1  # audio + its 1s delay (+ the tail hold)
    assert FFmpegManager.get_media_duration(str(out)) >= 6.0


def test_a_video_that_already_covers_its_audio_is_copied(tmp_path):
    video, audio = _make(tmp_path, 6.0, 2.0)
    out = VideoExporter._mux_track_for_concat(_ffmpeg(), video, str(audio), tmp_path, 1)
    assert abs(_video_len(out) - 6.0) < 0.2


def test_a_clip_of_another_size_is_scaled_to_the_target(tmp_path):
    video, audio = _make(tmp_path, 2.0, 1.0)  # 160x90
    out = VideoExporter._mux_track_for_concat(
        _ffmpeg(), video, str(audio), tmp_path, 2, target_size=(320, 200)
    )
    assert VideoExporter._video_size(out) == (320, 200)


def test_the_target_size_is_the_timeline_resolution_or_the_most_common_size(tmp_path):
    a, _ = _make(tmp_path, 1.0, 1.0)
    tracks = [{"file_path": str(a)}]
    assert VideoExporter._timeline_size({"resolution": {"width": 1920, "height": 1080}}, tracks) == (1920, 1080)
    assert VideoExporter._timeline_size({}, tracks) == (160, 90)


def _clip(tmp_path, name, seconds, fps, audio_seconds=None):
    v = tmp_path / f"{name}.mp4"
    subprocess.run([_ffmpeg(), "-y", "-f", "lavfi", "-i", f"color=c=red:s=160x90:r={fps}:d={seconds}",
                    "-pix_fmt", "yuv420p", str(v)], check=True, capture_output=True)
    a = None
    if audio_seconds:
        a = tmp_path / f"{name}.wav"
        subprocess.run([_ffmpeg(), "-y", "-f", "lavfi", "-i", f"sine=duration={audio_seconds}", str(a)],
                       check=True, capture_output=True)
    return {"file_path": str(v), "audio_path": str(a) if a else None}


def _stream_lengths(path):
    fp = _ffmpeg().replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg.EXE", "ffprobe.exe")
    import json
    j = json.loads(subprocess.run([fp, "-v", "error", "-show_streams", "-of", "json", str(path)],
                                  capture_output=True, encoding="utf-8").stdout)
    return {s["codec_type"]: float(s["duration"]) for s in j["streams"]}


def test_joined_video_keeps_audio_and_video_in_step_across_frame_rates(tmp_path):
    tracks = [
        _clip(tmp_path, "a", 3.0, 30, audio_seconds=2.0),
        {**_clip(tmp_path, "b", 4.0, 24, audio_seconds=3.0), "fade_into_next_seconds": 0.5},
        _clip(tmp_path, "c", 3.0, 24, audio_seconds=2.0),
        _clip(tmp_path, "d", 2.0, 25),
    ]
    out = tmp_path / "joined.mp4"
    VideoExporter.concat_from_timeline({"video_tracks": tracks, "fps": 30}, str(out))
    lengths = _stream_lengths(out)
    assert abs(lengths["video"] - lengths["audio"]) < 0.3
    assert lengths["video"] > 11.0  # 3 + (4 + 0.5 + 3 dissolve) + 2
