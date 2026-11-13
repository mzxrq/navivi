"""Haversine distances along a route."""

import math


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
