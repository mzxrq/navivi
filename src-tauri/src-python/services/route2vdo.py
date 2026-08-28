"""
Route to Video Animator (route2vdo.py)
---------------------------------------------------------------------------
Main Orchestrator. Parses CLI arguments and JSON data, then routes
the drawing commands to either the Spatial or Storyboard renderers.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
from html import parser
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from services.graphic_engine import GraphicsEngine
from services.logger import setup_logger
from services.spatial_renderer import SpatialRenderer
from services.storyboard_renderer import StoryboardRenderer
from services.vdo_exporter import VideoExporter
from services.pydeck_recorder import record_headless_video

# Logging configuration
logger = setup_logger("RouteAnimator")


class RouteAnimator:
    """Orchestrates the animation pipeline by bridging configurations with Renderers."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config

        settings = self.config.get("settings", {}) if self.config else {}
        map_font_size = settings.get("map_font_size", 20)

        # 1. Initialize the Core Graphics Engine
        self.graphics = GraphicsEngine(
            line_color=self.config.get("line_color", (0, 200, 255)),
            line_thickness=self.config.get("line_thickness", 10),
            marker_color=self.config.get("marker_color", (0, 0, 255)),
            marker_radius=self.config.get("marker_radius", 18),
            font_size=map_font_size,
        )

        self.out_dir = Path(config.get("output_dir", ""))
        self.out_dir.mkdir(parents=True, exist_ok=True)

        # 2. Initialize the isolated Render Engines
        self.spatial_renderer = SpatialRenderer(
            self.config, self.graphics, self.out_dir
        )
        self.storyboard_renderer = StoryboardRenderer(
            self.config, self.graphics, self.out_dir
        )

    def load_route_data(self, json_path: str) -> Tuple[List, List, List, Dict]:
        """Loads and parses the waypoints into memory."""
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            route_data, settings = data, {}
        else:
            route_data = data.get("route", data.get("points", []))
            settings = data.get("settings", {})

        points, labels, popups = [], [], []
        for item in route_data:
            if isinstance(item, (list, tuple)):
                points.append([float(item[0]), float(item[1])])
                labels.append(None)
                popups.append(None)
            elif isinstance(item, dict):
                points.append([float(item["x"]), float(item["y"])])
                labels.append(item.get("label"))
                # ADDED: Check for 'transition' key in the JSON configuration
                if (
                    "freeze_seconds" in item
                    or "popup_image" in item
                    or "popup_video" in item
                    or "transition" in item
                ):
                    popups.append(
                        {
                            "freeze_seconds": float(item.get("freeze_seconds", 2.0)),
                            "popup_image": item.get("popup_image"),
                            "popup_video": item.get("popup_video"),
                            "image_display": item.get(
                                "image_display", item.get("image display", "box")
                            ),
                            # ADDED: Store the transition type (e.g., 'pop up', 'fullscreen')
                            "transition": item.get("transition", "popup"),
                            "triggered": False,
                        }
                    )
                else:
                    popups.append(None)
            else:
                raise ValueError(f"Unknown point format: {item}")

        return points, labels, popups, settings

    def _freeze_video_end(self, video_path: str, hold_seconds: float):
        """Uses FFmpeg tpad filter to seamlessly clone and hold the final frame."""
        if hold_seconds <= 0:
            return

        logger.info(
            f"❄️ Freezing the final overview frame for {hold_seconds} seconds..."
        )
        temp_out = str(
            Path(video_path).with_name(f"temp_frozen_{Path(video_path).name}")
        )

        # FFmpeg command to pad the end of the video by cloning the last frame
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vf",
            f"tpad=stop_mode=clone:stop_duration={hold_seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            temp_out,
        ]

        result = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        if result.returncode == 0 and os.path.exists(temp_out):
            os.replace(temp_out, video_path)
        else:
            logger.warning("Failed to freeze video end. Skipping freeze frame.")

    def render(
        self,
        img_path: str,
        points: List,
        labels: List,
        popups: List,
        fps: int = 30,
        res_sequence: Optional[List] = None,
        summary: Optional[Dict] = None,
        wp_indices: Optional[List[int]] = None,
        **kwargs,
    ) -> List[str]:
        """Main rendering orchestrator. Decides which rendering engine to use."""
        if not os.path.exists(img_path):
            logger.error(f"Background path does not exist: {img_path}")
            raise FileNotFoundError(f"Background path does not exist: {img_path}")

        output_paths = []

        if self.config.get("use_leg_storyboard", False) and wp_indices:
            storyboard = self.storyboard_renderer.build_storyboard_from_route(
                points=points,
                labels=labels,
                popups=popups,
                wp_indices=wp_indices,
                leg_durations=self.config.get("leg_durations"),
                default_transition_hold_seconds=self.config.get(
                    "default_transition_hold_seconds", 1.5
                ),
                video_id="overview",
                output_filename="01_overview.mp4",
            )

            overview_path = self.storyboard_renderer.render_storyboard(
                bg_path=img_path,
                points=points,
                labels=labels,
                storyboard=storyboard,
                summary=summary,
            )
            # Sync the last frame state back for downstream usage
            self.spatial_renderer.last_frame = self.storyboard_renderer.last_frame

            with open(
                self.out_dir / "auto_storyboard.json", "w", encoding="utf-8"
            ) as f:
                json.dump(storyboard, f, indent=2, ensure_ascii=False)

            actions = storyboard.get("actions", [])
            timeline_tracks = self.storyboard_renderer.last_timeline_tracks

            if timeline_tracks and len(timeline_tracks) == len(actions):
                combined_clips = []
                current_group: List[str] = []
                leg_idx = 0

                # Single O(A) pass: partition the flat clip list into
                # per-leg groups every time a new "draw_route" action starts.
                for track, action in zip(timeline_tracks, actions):
                    a_type = action.get("type", "")

                    if a_type == "draw_route" and current_group:
                        out_name = str(
                            self.out_dir / f"01_overview_leg_{leg_idx:02d}.mp4"
                        )
                        VideoExporter.concat_clips(current_group, out_name)
                        combined_clips.append(out_name)
                        current_group = []
                        leg_idx += 1

                    current_group.append(track["file_path"])

                # Flush and merge the final group (last leg + summary/popup)
                if current_group:
                    out_name = str(self.out_dir / f"01_overview_leg_{leg_idx:02d}.mp4")
                    VideoExporter.concat_clips(current_group, out_name)
                    combined_clips.append(out_name)

                if combined_clips:
                    last_leg_path = combined_clips[-1]
                    self._freeze_video_end(
                        last_leg_path, hold_seconds=self.config.get("summary_hold", 4.0)
                    )

                output_paths.extend(combined_clips)

            elif overview_path:
                logger.warning(
                    "Storyboard timeline manifest missing/mismatched — "
                    "falling back to single stitched overview file."
                )
                self._freeze_video_end(
                    overview_path, hold_seconds=self.config.get("summary_hold", 4.0)
                )
                output_paths.append(overview_path)

        # Fallback to the Legacy Proximity Renderer
        else:
            overview_path = self.spatial_renderer.render_overview(
                img_path, points, labels, popups, fps, summary=summary
            )
            if overview_path:
                self._freeze_video_end(
                    overview_path, hold_seconds=self.config.get("summary_hold", 4.0)
                )
                output_paths.append(overview_path)

        # Always render waypoints using the spatial engine, OR PyDeck if requested
        if res_sequence:
            if self.config.get("use_3d_res", True):
                logger.info(
                    "Attempting Residential Sequence using 3D PyDeck (Split by Leg)..."
                )
                try:
                    res_route_path = self.config.get("res_route_path")
                    res_out_path = str(self.out_dir / "02_residential_map.mp4")

                    audio_durs = [
                        seg.get("segment_duration", 0.0) for seg in res_sequence
                    ]
                    final_res_paths = record_headless_video(
                        res_route_path,
                        res_out_path,
                        audio_durations=audio_durs,
                        speed_kmh=60,
                    )

                    if not final_res_paths:
                        raise RuntimeError(
                            "3D rendering generated an empty output sequence."
                        )

                    output_paths.extend(final_res_paths)

                except Exception as e:
                    logger.warning(
                        f"3D Rendering failed ({e}). Attempting 2D Fallback..."
                    )

                if res_sequence and res_sequence[0].get("img_path"):
                    res_paths = self.spatial_renderer.render_waypoints(
                        res_sequence, fps
                    )
                    output_paths.extend(res_paths)
                else:
                    logger.error(
                        "2D fallback skipped because 2D map images were bypassed to save time."
                    )
            else:
                logger.info(
                    "🗺️ Rendering Residential Sequence using 2D SpatialRenderer..."
                )
                res_paths = self.spatial_renderer.render_waypoints(res_sequence, fps)
                output_paths.extend(res_paths)

        return output_paths


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", required=True)
    parser.add_argument("--route", required=True)
    parser.add_argument("--output", default="data\\outputs\\video")
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--fps", type=int, default=None)
    parser.add_argument("--thickness", type=int, default=None)
    parser.add_argument("--radius", type=int, default=None)
    parser.add_argument("--res-map", default=None)
    parser.add_argument("--res-route", default=None)
    parser.add_argument("--res-duration", type=float, default=12.0)
    parser.add_argument("--pause", type=float, default=2.0)
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--summary-hold", type=float, default=4.0)
    parser.add_argument("--summary-fade", type=float, default=0.5)
    parser.add_argument(
        "--use-storyboard", action="store_true", help="Slice the overview video"
    )

    args = parser.parse_args()

    config = {
        "output_dir": args.output,
        "pause": args.pause,
        "summary_hold": args.summary_hold,
        "summary_fade": args.summary_fade,
        "res_duration": args.res_duration,
        "use_leg_storyboard": args.use_storyboard,
    }

    animator = RouteAnimator(config)
    points, labels, popups, settings = animator.load_route_data(args.route)

    animator.config["fps"] = args.fps or settings.get("fps", 30)
    animator.config["duration"] = args.duration or settings.get("duration_seconds", 8)
    animator.graphics.line_thickness = args.thickness or settings.get(
        "line_thickness", 10
    )
    animator.graphics.marker_radius = args.radius or settings.get("marker_radius", 18)

    res_sequence = None
    if args.res_route and args.res_map:
        res_points, res_labels, res_popups, _ = animator.load_route_data(args.res_route)

        try:
            out_path = Path(args.output)
            job_paths = [
                out_path / "job_config.json",
                out_path.parent / "job_config.json",
            ]

            for jp in job_paths:
                if jp.exists():
                    with open(jp, "r", encoding="utf-8") as f:
                        job_data = json.load(f)
                        start_lbl = job_data.get("start_point", {}).get("label")
                        end_lbl = job_data.get("end_point", {}).get("label")

                        if start_lbl and len(res_labels) > 0:
                            res_labels[0] = start_lbl
                        if end_lbl and len(res_labels) > 1:
                            res_labels[-1] = end_lbl
                    break
        except Exception as e:
            logger.warning(
                f"Could not read labels from job_config.json for residential map: {e}"
            )

        res_sequence = [
            {
                "img_path": args.res_map,
                "points": res_points,
                "labels": res_labels,
                "popups": res_popups,
            }
        ]

    summary = (
        json.load(open(args.summary_json, "r", encoding="utf-8"))
        if args.summary_json
        else None
    )

    wp_indices = [i for i, pop in enumerate(popups) if pop is not None]

    if 0 not in wp_indices:
        wp_indices.insert(0, 0)
    if len(points) - 1 not in wp_indices:
        wp_indices.append(len(points) - 1)

    output_files = animator.render(
        img_path=args.map,
        points=points,
        labels=labels,
        popups=popups,
        res_sequence=res_sequence,
        summary=summary,
        wp_indices=wp_indices,
    )

    logger.info(f"Rendered {len(output_files)} file(s):")
    for f in output_files:
        logger.info(f"   {f}")


if __name__ == "__main__":
    main()

Route2VDO = RouteAnimator
