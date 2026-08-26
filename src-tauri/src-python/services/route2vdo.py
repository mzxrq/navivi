"""
Route to Video Animator (route2vdo.py)
---------------------------------------------------------------------------
Main Orchestrator. Parses CLI arguments and JSON data, then routes
the drawing commands to either the Spatial or Storyboard renderers.
---------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from services.graphic_engine import GraphicsEngine
from services.logger import setup_logger
from services.spatial_renderer import SpatialRenderer
from services.storyboard_renderer import StoryboardRenderer

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
                if (
                    "freeze_seconds" in item
                    or "popup_image" in item
                    or "popup_video" in item
                ):
                    popups.append(
                        {
                            "freeze_seconds": float(item.get("freeze_seconds", 2.0)),
                            "popup_image": item.get("popup_image"),
                            "popup_video": item.get("popup_video"),
                            "image_display": item.get(
                                "image_display", item.get("image display", "box")
                            ),
                            "triggered": False,
                        }
                    )
                else:
                    popups.append(None)
            else:
                raise ValueError(f"Unknown point format: {item}")

        return points, labels, popups, settings

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

        base_img = self.graphics.read_image_safe(img_path)
        if base_img is None:
            logger.error(f"Cannot read: {img_path}")
            raise FileNotFoundError(f"Cannot read: {img_path}")

        output_paths = []

        # 💡 Route to Storyboard Renderer if the timeline strategy is enabled
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
                img_path=img_path,
                points=points,
                labels=labels,
                storyboard=storyboard,
                summary=summary,
            )
            # Sync the last frame state back for downstream usage
            self.spatial_renderer.last_frame = self.storyboard_renderer.last_frame

        # 💡 Fallback to the Legacy Proximity Renderer
        else:
            overview_path = self.spatial_renderer.render_overview(
                base_img, points, labels, popups, fps, summary=summary
            )

        if overview_path:
            output_paths.append(overview_path)

        # 💡 Always render waypoints using the spatial engine
        if res_sequence:
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

    args = parser.parse_args()

    config = {
        "output_dir": args.output,
        "pause": args.pause,
        "summary_hold": args.summary_hold,
        "summary_fade": args.summary_fade,
        "res_duration": args.res_duration,
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
        res_points, res_labels, _, _ = animator.load_route_data(args.res_route)
        res_sequence = [
            {"img_path": args.res_map, "points": res_points, "labels": res_labels}
        ]

    summary = (
        json.load(open(args.summary_json, "r", encoding="utf-8"))
        if args.summary_json
        else None
    )

    output_files = animator.render(
        img_path=args.map,
        points=points,
        labels=labels,
        popups=popups,
        res_sequence=res_sequence,
        summary=summary,
    )

    print(f"✅ Rendered {len(output_files)} file(s):")
    for f in output_files:
        print(f"   {f}")


if __name__ == "__main__":
    main()

Route2VDO = RouteAnimator
