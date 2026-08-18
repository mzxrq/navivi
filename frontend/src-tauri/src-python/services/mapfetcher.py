"""
Map Fetcher Service (mapfetcher.py)
"""
'''
This module provides a service for fetching map data from various sources. It is designed to be used within the Tauri application framework, allowing for seamless integration with the frontend.

How to Use:
"""
# 1. Import the file (Python automatically looks in the same folder)
import mapfetcher

# 2. Call a function or class from inside that file.
map_data = mapfetcher.fetch_map(lat=40.7128, lng=-74.0060)

# Alternatively, import a specific function directly:
from mapfetcher import fetch_map

map_data = fetch_map(lat=40.7128, lng=-74.0060)
"""
'''

# Import necessary modules
import logging
from pathlib import Path
from typing import Final, List
import contextily as cx
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image
from scipy.interpolate import make_interp_spline

# Import custom modules
from job_config import JobConfigManager

# Define Final constants for map fetching
TARGET_ASPECT_RATIO: Final[float] = 16 / 9
MIN_MAP_WIDTH: Final[int] = 1280

# DEFINE Path for the cache directory
CACHE_DIR = Path(".cache") / "mapfetcher"

class MapFetcher:
    """
    A class to fetch map data from various sources and handle map-related operations.
    """

    # =========================
    # Initialization
    # =========================
    def __init__(self, config : JobConfigManager):
        self.config = config

        # Pull required settings from the job configuration
        self.project_name = self.config.get("project_name")
        self.directory_path = Path(self.config.get("directory_path"))
        self.fps = self.config.get_settings().get("fps", 30)

    # ==========================
    # Map fetching operations
    # ==========================
    def get_bounding_box(self, waypoints: pd.DataFrame, padding: float = 0.0) -> tuple:
        """
        Calculate the bounding box for the given waypoints.
        """
        # 1. Check if waypoints DataFrame is empty
        if waypoints.empty:
            raise ValueError("Waypoints DataFrame is empty. Cannot calculate bounding box.")

        # 2. Calculate min and max lat and lng
        min_lat = waypoints['lat'].min()
        max_lat = waypoints['lat'].max()
        min_lon = waypoints['lng'].min()
        max_lon = waypoints['lng'].max()

        # 3. Apply padding if specified
        if padding > 0:
            lat_range = max_lat - min_lat
            lon_range = max_lon - min_lon
            min_lat -= lat_range * padding
            max_lat += lat_range * padding
            min_lon -= lon_range * padding
            max_lon += lon_range * padding

        return (min_lat, max_lat, min_lon, max_lon)

    # ==========================
    # douglas-peucker algorithm for path simplification
    # ==========================
    def douglas_peucker(self, points: np.ndarray, epsilon: float) -> np.ndarray:
        """
        Simplify a path using the Douglas-Peucker algorithm.
        """

        # 1. Check if points array is empty
        if points.size == 0:
            raise ValueError("Points array is empty. Cannot simplify path.")

        # 2. If there are 2 or fewer points, nothing to simplify
        if len(points) <= 2:
            return points

        start, end = points[0], points[-1]
        
        # 3. Use only X, Y (or lat, lon -> columns 0 and 1) for geometric distance calculation
        p_xy = points[:, :2]
        start_xy = start[:2]
        end_xy = end[:2]

        line_vec = end_xy - start_xy
        line_len = np.linalg.norm(line_vec)

        if line_len == 0:
            return np.array([start])

        line_unit_vec = line_vec / line_len
        
        # 4. Calculate the perpendicular distances from each point to the line segment
        v = p_xy - start_xy
        distances = np.abs(v[:, 0] * (-line_unit_vec[1]) + v[:, 1] * line_unit_vec[0])

        max_distance_index = np.argmax(distances)
        max_distance = distances[max_distance_index]

        # If the maximum distance is greater than epsilon, recursively simplify
        if max_distance > epsilon:
            # 5. Recursively simplify the left and right segments
            left_points = self.douglas_peucker(points[:max_distance_index + 1], epsilon)
            right_points = self.douglas_peucker(points[max_distance_index:], epsilon)

            # 6. Combine results, dropping the duplicate connecting point
            return np.vstack((left_points[:-1], right_points))
        else:
            return np.array([start, end])

    # ==========================
    # Get smoothed path using spline interpolation
    # ==========================
    def get_smoothed_path(self, points: np.ndarray, num_points: int = 100) -> np.ndarray:
        """
        Smooth a path using spline interpolation.
        """
        # 1. Check if points array is empty
        if points.size == 0:
            raise ValueError("Points array is empty. Cannot smooth path.")

        # 2. If there are fewer than 3 points, return the original points
        if len(points) < 3:
            return points

        # 3. Use only X, Y (or lat, lon -> columns 0 and 1) for smoothing
        x = points[:, 0]
        y = points[:, 1]

        # 4. Create a parameter t for the spline
        t = np.linspace(0, 1, len(points))
        
        # 5. Create a new parameter t_new for the smoothed path
        t_new = np.linspace(0, 1, num_points)

        # 6. Create spline functions for x and y
        spline_x = make_interp_spline(t, x)
        spline_y = make_interp_spline(t, y)

        # 7. Evaluate the splines at the new parameter values
        x_smooth = spline_x(t_new)
        y_smooth = spline_y(t_new)

        return np.column_stack((x_smooth, y_smooth))

    # ==========================
    # Fetch map tiles and create a composite image
    # ==========================
    def fetch_map(self, bounding_box: tuple, zoom: int = 15) -> Image.Image:
        """
        Fetch map tiles for the given bounding box and create a composite image.
        """
        # 1. Check if bounding box is valid
        if len(bounding_box) != 4:
            raise ValueError("Bounding box must be a tuple of (min_lat, max_lat, min_lon, max_lon).")

        min_lat, max_lat, min_lon, max_lon = bounding_box

        try:
            fig, ax = plt.subplots(figsize=(10, 10))
            
            # Set the limits FIRST so contextily knows the exact size of the map
            ax.set_xlim(min_lon, max_lon)
            ax.set_ylim(min_lat, max_lat)
            ax.axis('off')
            
            # Add the basemap. 
            # By omitting the 'zoom' parameter, contextily will automatically 
            # calculate the best zoom level based on the xlim and ylim we just set.
            cx.add_basemap(ax, crs="EPSG:4326")

            # 3. Save the figure to a temporary file
            temp_map_path = CACHE_DIR / f"map_{min_lat}_{max_lat}_{min_lon}_{max_lon}.png"
            temp_map_path.parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(temp_map_path, bbox_inches='tight', pad_inches=0)
            plt.close(fig)

            # 4. Open the saved image and return it
            return Image.open(temp_map_path)

        except Exception as e:
            logging.error(f"Failed to fetch map: {e}")
            raise

    # ==========================
    # Additional utility methods can be added here
    # =========================

    # =========================
    # Crop and resize the map image to fit the target aspect ratio
    # =========================
    def crop_and_resize_map(self, map_image: Image.Image, target_aspect_ratio: float = TARGET_ASPECT_RATIO) -> Image.Image:
        """
        Crop and resize the map image to fit the target aspect ratio.
        """
        # 1. Get the current size of the image
        width, height = map_image.size
        current_aspect_ratio = width / height

        # 2. Determine how to crop based on the aspect ratio
        if current_aspect_ratio > target_aspect_ratio:
            # Image is too wide, crop width
            new_width = int(height * target_aspect_ratio)
            left = (width - new_width) // 2
            right = left + new_width
            top = 0
            bottom = height
        else:
            # Image is too tall, crop height
            new_height = int(width / target_aspect_ratio)
            top = (height - new_height) // 2
            bottom = top + new_height
            left = 0
            right = width

        # 3. Crop the image
        cropped_image = map_image.crop((left, top, right, bottom))

        # 4. Resize the image to meet minimum width requirements while maintaining aspect ratio
        if cropped_image.width < MIN_MAP_WIDTH:
            new_height = int(MIN_MAP_WIDTH / target_aspect_ratio)
            resized_image = cropped_image.resize((MIN_MAP_WIDTH, new_height), Image.Resampling.LANCZOS)
            return resized_image

        return cropped_image

    # ==========================
    # Get residential map image for the project
    # ==========================
    def get_residential_map(self) -> Image.Image:
        """
        Get the residential map image for the project based on waypoints.
        """
        # 1. Load waypoints from the job configuration
        waypoints = pd.DataFrame(self.config.get_waypoints())

        # 2. Check if waypoints are available
        if waypoints.empty:
            raise ValueError("No waypoints available in the job configuration.")

        # 3. Calculate the bounding box with padding
        bounding_box = self.get_bounding_box(waypoints, padding=0.05)

        # 4. Fetch the map image for the bounding box
        map_image = self.fetch_map(bounding_box)

        # 5. Crop and resize the map image to fit the target aspect ratio
        final_map_image = self.crop_and_resize_map(map_image)

        return final_map_image

    # ==========================
    # Generate residential map sequence for the project
    # ==========================
    def generate_residential_map_sequence(self) -> List[Image.Image]:
            """
            Generate a sequence of residential map images by downloading one large map 
            and cropping localized frames to prevent API rate-limiting and improve speed.
            """
            # 1. Load waypoints from the job configuration
            waypoints = pd.DataFrame(self.config.get_waypoints())

            if waypoints.empty:
                raise ValueError("No waypoints available in the job configuration.")

            waypoints = waypoints.rename(columns={
                "latitude": "lat", 
                "longitude": "lng", 
                "lon": "lng"
            })

            # 2. Simplify and smooth the path
            simplified_points = self.douglas_peucker(waypoints[['lat', 'lng']].to_numpy(), epsilon=0.0001)
            smoothed_points = self.get_smoothed_path(simplified_points, num_points=100)

            # 3. Calculate the "Master Bounding Box" for the entire smoothed path.
            # We add a 0.01 padding to ensure the camera window doesn't go off the edge 
            # when we are at the very start or end of the route.
            min_lat = np.min(smoothed_points[:, 0]) - 0.01
            max_lat = np.max(smoothed_points[:, 0]) + 0.01
            min_lon = np.min(smoothed_points[:, 1]) - 0.01
            max_lon = np.max(smoothed_points[:, 1]) + 0.01
            
            master_bbox = (min_lat, max_lat, min_lon, max_lon)

            # 4. Fetch the single large map (Only ONE network request!)
            logging.info("Fetching master map for sequence generation...")
            master_map = self.fetch_map(master_bbox)
            map_width, map_height = master_map.size

            # 5. Define the "Camera Window" size in pixels. 
            # Your original code used a 0.02 degree radius (lat-0.01 to lat+0.01).
            # Here we translate that 0.02 degree scale into pixels.
            lat_range = max_lat - min_lat
            lon_range = max_lon - min_lon
            
            crop_width_px = int((0.02 / lon_range) * map_width)
            crop_height_px = int((0.02 / lat_range) * map_height)

            # 6. Loop through points and dynamically crop from the master map
            map_sequence = []
            for point in smoothed_points:
                lat, lon = point
                
                # Map Lat/Lon coordinates to X/Y pixel coordinates on the image
                # Note: Y is calculated from max_lat because image Y=0 is the TOP of the map
                pixel_x = int(((lon - min_lon) / lon_range) * map_width)
                pixel_y = int(((max_lat - lat) / lat_range) * map_height)
                
                # Calculate crop boundaries
                left = pixel_x - (crop_width_px // 2)
                right = pixel_x + (crop_width_px // 2)
                top = pixel_y - (crop_height_px // 2)
                bottom = pixel_y + (crop_height_px // 2)
                
                # Crop the frame directly from memory (Instantaneous)
                frame = master_map.crop((left, top, right, bottom))
                
                # Pass through your existing resizer
                final_frame = self.crop_and_resize_map(frame)
                map_sequence.append(final_frame)

            logging.info(f"Successfully generated {len(map_sequence)} map frames.")
            return map_sequence


