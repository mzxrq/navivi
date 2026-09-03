"""Math & geo helpers: bearings, offsets, and haversine distance."""

import math


def calculate_bearing(lon1, lat1, lon2, lat2):
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (
        math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    )
    initial_bearing = math.atan2(x, y)
    return (math.degrees(initial_bearing) + 360) % 360


def smooth_bearings(bearings, alpha=0.15):
    if not bearings:
        return []
    smoothed = [bearings[0]]
    current = bearings[0]
    for b in bearings[1:]:
        diff = ((b - current + 180) % 360) - 180
        current = (current + alpha * diff) % 360
        smoothed.append(current)
    return smoothed


def offset_point(lon, lat, bearing_deg, distance_m):
    R = 6371000.0
    bearing_rad = math.radians(bearing_deg)
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    ang_dist = distance_m / R

    lat2 = math.asin(
        math.sin(lat_rad) * math.cos(ang_dist)
        + math.cos(lat_rad) * math.sin(ang_dist) * math.cos(bearing_rad)
    )
    lon2 = lon_rad + math.atan2(
        math.sin(bearing_rad) * math.sin(ang_dist) * math.cos(lat_rad),
        math.cos(ang_dist) - math.sin(lat_rad) * math.sin(lat2),
    )
    return math.degrees(lon2), math.degrees(lat2)


def haversine_km(lon1, lat1, lon2, lat2):
    R = 6371.0
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * R * math.asin(math.sqrt(a))


def cumulative_distance_km(lons, lats):
    cum = [0.0]
    for i in range(1, len(lons)):
        cum.append(cum[-1] + haversine_km(lons[i - 1], lats[i - 1], lons[i], lats[i]))
    return cum
