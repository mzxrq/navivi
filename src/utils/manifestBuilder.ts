import { AssetManifest, ManifestSegment } from "../types/manifest";
import { Waypoint, ProjectSettings } from "../types";

export function buildAssetManifest(
  projectId: string,
  waypoints: Waypoint[],
  settings: ProjectSettings
): AssetManifest {
  const segments: ManifestSegment[] = [];

  for (let i = 0; i < waypoints.length; i++) {
    const wp = waypoints[i];

    // 1. Route Animation Segment (Transition to this waypoint)
    if (i > 0) {
      const prevWp = waypoints[i - 1];
      segments.push({
        id: `route_${prevWp.id}_to_${wp.id}`,
        name: `Route: ${prevWp.name} to ${wp.name}`,
        type: "route_animation",
        duration_sec: 5.0, // Default duration, could be calculated based on distance/speed
        map_animation: {
          start_coord: [prevWp.lng, prevWp.lat],
          end_coord: [wp.lng, wp.lat],
          zoom: 14,
          pitch: 60,
          route_mode: prevWp.routeMode,
          custom_marker: wp.customMarker,
          draw_style: prevWp.drawStyle,
          curve_offset: prevWp.curveOffset
        }
      });
    }

    // 2. Location Media Segment (Arriving at waypoint)
    const locationMedia: any[] = [];
    if (wp.images && wp.images.length > 0) {
      wp.images.forEach((imgPath, idx) => {
        locationMedia.push({
          type: imgPath.endsWith(".mp4") ? "video" : "image",
          file_path: imgPath,
          pan_zoom_effect: wp.imagePans?.[idx] || "none",
          transition_to_next: wp.imageTransitions?.[idx] || "fade"
        });
      });
    }

    // Only create a location segment if there's media or narration to play
    if (locationMedia.length > 0 || wp.audioUrl || wp.narration || wp.arrivingNarration || wp.attractionNarration) {
      segments.push({
        id: `loc_${wp.id}`,
        name: `Location: ${wp.name}`,
        type: "location_media",
        duration_sec: (locationMedia.length * 5) || 5, // 5s per media item
        visuals: locationMedia,
        narration: wp.audioUrl || wp.narration || wp.arrivingNarration || wp.attractionNarration ? {
          audio_path: wp.audioUrl,
          start_time_offset: 0.5,
          base_text: wp.narration,
          arriving_text: wp.arrivingNarration,
          attraction_text: wp.attractionNarration
        } : undefined,
        subtitles: wp.audioUrl ? {
          srt_path: wp.audioUrl.replace(/\.[^/.]+$/, ".srt")
        } : undefined
      });
    }
  }

  return {
    project_id: projectId,
    version: "1.0",
    global_settings: {
      resolution: { width: 1920, height: 1080 },
      fps: settings.fps || 30,
      line_color: settings.line_color
    },
    segments
  };
}

