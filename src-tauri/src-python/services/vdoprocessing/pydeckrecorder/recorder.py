"""Route-line GeoJSON features shared by the leg and overview renderers (pedestrian.py, overview_pydeck.py)."""


def _route_linestring_feature(coords_lonlat: list, line_color: list) -> dict:
    """A single-feature GeoJSON FeatureCollection wrapping `coords_lonlat`
    (already [lon, lat] pairs, matching GeoJSON's own axis order) as a
    LineString -- the shape pdk.Layer("GeoJsonLayer", ...) expects for its
    `data`. `line_color` rides along in "properties" rather than as a
    layer-level constant so get_line_color can read it per-feature the way
    GeoJsonLayer is designed to be driven."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords_lonlat},
                "properties": {"line_color": line_color},
            }
        ],
    }


def _route_gradient_feature(coords_lonlat: list, segment_colors: list) -> dict:
    """Like `_route_linestring_feature`, but one colour per segment (`segment_colors[i]` colours point i -> i+1):
    runs of equal colour become one LineString feature, neighbours sharing their joint vertex so the line stays
    unbroken. Fewer segment colours than segments reuse the last one (a trail's partial tail segment)."""
    n = len(coords_lonlat)
    if n < 2 or not segment_colors:
        return {"type": "FeatureCollection", "features": []}
    colors = [segment_colors[min(i, len(segment_colors) - 1)] for i in range(n - 1)]
    features = []
    start = 0
    for i in range(1, n):
        if i == n - 1 or colors[i] != colors[start]:
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords_lonlat[start:i + 1]},
                "properties": {"line_color": colors[start]},
            })
            start = i
    return {"type": "FeatureCollection", "features": features}
