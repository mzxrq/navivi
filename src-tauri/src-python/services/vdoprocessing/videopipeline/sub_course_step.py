"""The sub course's clips: the main pipeline's per-stop steps run again on its own small project
(services/config/sub_course.py), inside the route stage, then its clips go into timeline.json before the outro."""

import copy
import json
from pathlib import Path
from typing import Optional

from services import tuning
from services.config.job_config import JobConfigManager
from services.config.sub_course import sub_course_name, write_sub_config
from services.config.upscaled_images import upscale_enabled
from services.localization.subtitle import caption_layout
from services.logger.progress import tracker
from services.projectfiles import write_json_atomic

from .attraction_step import render_attraction_videos
from .audio_step import apply_cued_scripts, generate_audio, stop_tts_server
from .gps_step import process_gps
from .helpers import logger, project_subtitle_dir
from .leg_pieces import compute_leg_narration_splits
from .narration_step import add_default_cues, record_cue_times
from .render_step import render_route_video
from .subtitle_step import build_attraction_subtitles, build_subtitles
from .timeline_step import build_timeline
from .upscale_step import upscale_waypoint_images


def render_sub_course(main_config_path: str, force: bool, attractions_on: bool, fast_render: bool) -> Optional[str]:
    """Makes the sub course's voice, subtitles, attraction clips and legs; returns its own timeline.json, or None
    when the project has no sub course. The main project's config is active again afterwards."""
    sub_path = write_sub_config(main_config_path)
    if sub_path is None:
        return None
    sub_dir = sub_path.parent
    try:
        tracker.show("Sub course: parsing its track...")
        cleaned = process_gps(str(sub_path))
        settings = JobConfigManager(sub_path).get("settings", {})
        use_cues = bool(settings.get("use_narration_cues", True))
        audio = {}
        if not fast_render:
            tracker.show("Sub course: voicing its stops...")
            add_default_cues(str(sub_path))
            audio = generate_audio(cleaned, str(sub_path), force=force)
            if use_cues:
                record_cue_times(str(sub_path), audio)
            stop_tts_server()

        waypoints = copy.deepcopy(JobConfigManager(sub_path).get("waypoints", []))
        subtitles, attraction_subtitles = [], []
        if not fast_render:
            apply_cued_scripts(waypoints, sub_dir)
            layout = caption_layout(settings)
            subtitle_dir = str(project_subtitle_dir(sub_dir))
            subtitles = build_subtitles(waypoints, audio.get("audio_paths", []), subtitle_dir, force=force, layout=layout)
            attraction_subtitles = build_attraction_subtitles(
                waypoints, audio.get("attraction_audio_paths", []), subtitle_dir, force=force, layout=layout,
            )
        if upscale_enabled(settings):
            upscale_waypoint_images(str(sub_path), force=force)

        attraction_videos = []
        if attractions_on:
            tracker.show("Sub course: attraction videos...")
            attraction_videos = render_attraction_videos(
                str(sub_path),
                audio_durations=audio.get("attraction_audio_durations"),
                audio_paths=audio.get("attraction_audio_paths"),
                force=force,
            )
            from services.vdoprocessing.comfyui_i2v_client import ComfyUII2VClient
            ComfyUII2VClient.stop_server()

        tracker.show("Sub course: rendering its legs...")
        video_paths = render_route_video(
            cleaned_route=cleaned,
            project_config_path=str(sub_path),
            output_video_dir=str(sub_dir / "assets" / "video" / "route"),
            audio_durations=audio.get("audio_durations"),
            audio_pauses=audio.get("audio_pauses"),
            force=force,
            render_mode="residential",
        )
        video_paths, splits = compute_leg_narration_splits(
            video_paths, audio.get("audio_paths"), subtitles, waypoints, str(sub_dir)
        )
        return build_timeline(
            video_paths=video_paths,
            attraction_videos=attraction_videos,
            final_videos=video_paths + attraction_videos,
            audio_paths=audio.get("audio_paths"),
            subtitle_paths=subtitles,
            project_dir=str(sub_dir),
            attraction_audio_paths=audio.get("attraction_audio_paths"),
            attraction_subtitle_paths=attraction_subtitles,
            leg_narration_splits=splits,
            attraction_fade_seconds=float(settings.get("attraction_fade_seconds", 0.8)),
            place_label_look=settings.get("place_label_look"),
            waypoints=waypoints,
        )
    finally:
        JobConfigManager(main_config_path)


def append_sub_course(timeline_path: str, sub_timeline_path: Optional[str], main_config_path: str) -> None:
    """Puts the sub course's clips into timeline.json after the main course (before the outro), the first one
    carrying the sub course's name as a still title."""
    if not sub_timeline_path:
        return
    with open(timeline_path, "r", encoding="utf-8") as f:
        main = json.load(f)
    with open(sub_timeline_path, "r", encoding="utf-8") as f:
        sub = json.load(f)
    sub_tracks = sub.get("video_tracks") or []
    if not sub_tracks:
        return
    with open(main_config_path, "r", encoding="utf-8") as f:
        config = json.load(f)
    stops = (config.get("sub_course") or {}).get("waypoints") or [{}]
    name = sub_course_name(config) or f"{stops[0].get('label', '')} → {stops[-1].get('label', '')}"
    merged, shift = merge_tracks(main, sub, name)
    write_json_atomic(Path(timeline_path), merged)
    logger.info("Sub course: %d clip(s) added to the timeline (%.1fs).", len(sub_tracks), shift)


def merge_tracks(main: dict, sub: dict, name: str) -> tuple[dict, float]:
    """`main` with `sub`'s clips inserted before its outro (or at its end); cues and texts after it move along."""
    tracks = list(main.get("video_tracks") or [])
    outro = len(tracks)
    if tracks and Path(tracks[-1].get("file_path") or "").name == tuning.OUTRO_OUTPUT_FILENAME:
        outro = len(tracks) - 1
    at = sum(float(t.get("duration") or 0.0) for t in tracks[:outro])
    shift = float(sub.get("total_duration_seconds") or sum(float(t.get("duration") or 0.0) for t in sub["video_tracks"]))

    def moved(items, base):
        return [{**x, "start": round(x["start"] + base, 3), "end": round(x["end"] + base, 3)} for x in items]

    before = lambda items: [x for x in items if x["start"] < at]  # noqa: E731
    after = lambda items: [x for x in items if x["start"] >= at]  # noqa: E731
    title = []
    if name:
        first = float(sub["video_tracks"][0].get("duration") or 0.0)
        title = [{
            "start": 0.0, "end": round(min(tuning.SUB_COURSE_TITLE_SECONDS, first), 3), "kind": "sub_course",
            "animation": "none", "position": "middle", "title": {"text": name},
        }]
        sub["video_tracks"][0] = {**sub["video_tracks"][0], "texts": title + (sub["video_tracks"][0].get("texts") or [])}
    out = dict(main)
    out["video_tracks"] = [
        {**t, "order": i} for i, t in enumerate(tracks[:outro] + sub["video_tracks"] + tracks[outro:])
    ]
    for key in ("subtitles", "texts"):
        extra = (sub.get(key) or []) + (title if key == "texts" else [])
        out[key] = before(main.get(key) or []) + moved(extra, at) + moved(after(main.get(key) or []), shift)
    out["total_duration_seconds"] = round(float(main.get("total_duration_seconds") or at) + shift, 3)
    return out, shift
