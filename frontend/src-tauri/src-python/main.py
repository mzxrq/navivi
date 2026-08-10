# ============================================================
# main.py — full pipeline: cleaned data -> big picture + residential video
# ============================================================
import sys
import json
import math
from pathlib import Path
from datetime import datetime

import pandas as pd

from services.gpsparser import (
    convert_gps_file,
    clean_gps_data,
    export_to_frontend_json,
    convert_gps_to_pixels,
    split_route_by_landmarks,          # from prior refactor
)
from services.filehandler import store_raw_file_with_datetime
from services.mapfetcher import (
    calculate_bounding_box,
    save_map_image,
    generate_residential_map_series_by_landmark,  # from prior refactor
)
from services.route2vdo import render_route_animation


def data_pipeline_process(input_file: str, output_format: str = "iblue747") -> str:
    print(f"Processing file: {input_file}")
    route = convert_gps_file(input_file=input_file, output_filename=input_file.replace(".TXT", ".csv"), output_format=output_format)
    cleaned_route = clean_gps_data(route)
    json_route = export_to_frontend_json(cleaned_route, original_input_path=input_file, project_name="Untitled Project")
    print(f"Pipeline completed successfully!")
    return json.dumps(json_route, ensure_ascii=False)


def store_raw_file(input_file: str) -> str:
    stored_file_path = store_raw_file_with_datetime(input_file)
    if stored_file_path:
        print(f"Raw file stored at: {stored_file_path}")
    else:
        print("Failed to store raw file.")
    return stored_file_path


def handle_incoming_gps_upload(raw_source_path: str) -> str:
    stored_path = store_raw_file(raw_source_path)
    if not stored_path:
        raise ValueError(f"Failed to store raw file from: {raw_source_path}")
    return data_pipeline_process(input_file=stored_path, output_format="iblue747")


def _next_video_path(source_stem: str, output_dir: Path) -> Path:
    """
    Collision-safe video output naming, matching the project-wide
    {stem}_{date}_{time}_{seq:02d}.mp4 convention used for raw/cleaned files.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    datetime_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    for seq in range(1, 100):
        candidate = output_dir / f"{source_stem}_video_{datetime_str}_{seq:02d}.mp4"
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not generate a unique video filename for {source_stem}.")


def save_route_video(
    cleaned_csv_path: str,
    output_dir: str = "data/outputs/video",
    tmp_map_dir: str = "data/outputs/maps",
) -> str:
    """
    Full pipeline stage: cleaned route CSV -> big-picture map + animation
    -> landmark-anchored residential maps -> stitched MP4.

    Orchestration only — all map math / rendering lives in mapfetcher.py
    and route2vdo.py, and pixel conversion lives in gpsparser.py. This
    function just sequences the stages and owns output naming/IO.
    """
    csv_path = Path(cleaned_csv_path)
    if not csv_path.exists():
        raise FileNotFoundError(f"Cleaned route CSV not found: {cleaned_csv_path}")

    print(f"Starting video pipeline for: {csv_path.name}")

    # 1. Reload the cleaned route (clean_gps_data already normalized/sorted it)
    route_df = pd.read_csv(csv_path)
    route_df.columns = [c.strip().lower() for c in route_df.columns]
    if route_df.empty:
        raise ValueError("Cleaned route is empty — nothing to render.")

    # img_url is all-NaN/empty at this point (clean_gps_data only flags
    # landmarks, it doesn't render images yet), so a plain CSV round-trip
    # gets pandas to infer this column as float64 (an all-NaN column has
    # no way to signal "this should hold strings" on its own). A simple
    # `.astype(object)` re-assignment can still leave the underlying block
    # eligible for re-inference in edge cases (empty masks, consolidated
    # blocks, re-runs against a stale float64 column already on disk), so
    # instead we unconditionally REPLACE the column with a freshly
    # allocated, guaranteed object-dtype array built from Python's own
    # None — this can never silently collapse back to float64 the way an
    # in-place astype() on existing float data sometimes does.
    if "img_url" in route_df.columns:
        existing_urls = route_df["img_url"].where(pd.notna(route_df["img_url"]), None).tolist()
        route_df["img_url"] = pd.Series(existing_urls, index=route_df.index, dtype=object)
    else:
        route_df["img_url"] = pd.Series([None] * len(route_df), index=route_df.index, dtype=object)

    out_dir = Path(output_dir)
    map_dir = Path(tmp_map_dir)
    map_dir.mkdir(parents=True, exist_ok=True)

    # 2. Big-picture background map (16:9, video-ready)
    bbox = calculate_bounding_box(route_df)
    big_map_path = str(map_dir / f"{csv_path.stem}_bigmap.png")
    extent, img_w, img_h = save_map_image(bbox, output_filename=big_map_path)

    # 3. Pixel-space conversion for the big-picture pass
    pixel_points = convert_gps_to_pixels(route_df, extent, big_map_path)
    labels = (
        route_df["store_name"].tolist()
        if "store_name" in route_df.columns
        else [None] * len(pixel_points)
    )
    if not pixel_points:
        raise ValueError("Pixel conversion produced no points — aborting render.")

    # 4. Landmark-anchored residential slices (len == waypoint/landmark count)
    chunks = split_route_by_landmarks(route_df)
    res_sequence = []
    if chunks:
        res_assets = generate_residential_map_series_by_landmark(
            route_chunks=chunks,
            source_filename=str(csv_path),
            output_dir=str(map_dir),
        )
        for asset in res_assets:
            res_pixels = convert_gps_to_pixels(asset["chunk_df"], asset["extent"], asset["map_file"])
            res_labels = (
                asset["chunk_df"]["store_name"].tolist()
                if "store_name" in asset["chunk_df"].columns
                else [None] * len(res_pixels)
            )
            res_sequence.append({
                "img_path": asset["map_file"],
                "points": [list(p) for p in res_pixels],
                "labels": res_labels,
            })

            # --- BINDING FIX -------------------------------------------------
            # mapfetcher renders a real PNG per landmark chunk and hands its
            # path back via asset["map_file"], but nothing previously wrote
            # that path onto route_df — clean_gps_data() only ever set
            # img_url to a placeholder ("" originally, now NaN) because no
            # image existed yet at that stage. Without this write-back,
            # export_to_frontend_json()'s `pd.notna(row.get("img_url"))`
            # check always fails and the popup_image the video already
            # references on disk never makes it into the JSON payload the
            # frontend/consumer reads — the file was rendered but orphaned.
            #
            # Match on the landmark's own coordinates (rounded to ~11cm
            # precision at 6 decimal places) rather than positional index,
            # since route_df here is the full, unsplit route and asset
            # only carries its chunk_df — coordinate identity is the only
            # stable join key split_route_by_landmarks preserves.
            landmark_mask = (
                (route_df["latitude"].round(6) == round(asset["center"][0], 6)) &
                (route_df["longitude"].round(6) == round(asset["center"][1], 6)) &
                (route_df["is_landmarked"] == True)
            )
            route_df.loc[landmark_mask, "img_url"] = asset["map_file"]
            # --------------------------------------------------------------
    else:
        print("No landmarks detected — skipping residential (Phase 3) slices.")

    # Persist the now-populated img_url column back to the cleaned CSV, and
    # re-export the frontend JSON so downstream consumers (and this run's
    # own video render) see the bound popup images rather than the stale,
    # pre-render placeholder values written at clean_gps_data() time.
    route_df.to_csv(csv_path, index=False)
    export_to_frontend_json(
        {"route": route_df, "waypoints": pd.DataFrame(), "saved_paths": {"route_file": str(csv_path)}},
        original_input_path=str(csv_path),
    )

    # 5. Render + stitch final MP4
    video_out = _next_video_path(csv_path.stem, out_dir)
    render_route_animation(
        img_path=big_map_path,
        points=[list(p) for p in pixel_points],
        labels=labels,
        popups=[None] * len(pixel_points),  # popups sourced separately if/when frontend sends them
        output_path=str(video_out),
        res_sequence=res_sequence or None, # type: ignore
    )

    print(f" Video pipeline complete → {video_out}")
    return str(video_out)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        payload = sys.argv[2] if len(sys.argv) > 2 else ""

        try:
            if command == "process_gps":
                result_json = handle_incoming_gps_upload(payload)
                print(result_json)
            elif command == "save_video":
                # payload = path to the *_cleaned_*.csv produced by clean_gps_data
                video_path = save_route_video(payload)
                print(video_path)
            else:
                print(f"Error: Unknown command '{command}'", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"Error: {str(e)}", file=sys.stderr)
            sys.exit(1)