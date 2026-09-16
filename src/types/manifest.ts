export interface AssetManifest {
  project_id: string;
  version: string;
  global_settings: {
    resolution: { width: number; height: number };
    fps: number;
    bg_music?: {
      path: string;
      volume: number;
      ducking_level: number;
      fade_duration: number;
    };
  };
  segments: ManifestSegment[];
}

export interface ManifestSegment {
  id: string;
  name: string;
  type: "route_animation" | "location_media";
  duration_sec: number;

  // Mapbox Animation (Fly-to, following route)
  map_animation?: {
    start_coord: [number, number]; // [lng, lat]
    end_coord: [number, number];
    zoom: number;
    pitch: number;
  };

  // Wan2.2 AI Video / Images
  visuals?: {
    type: "video" | "image";
    file_path: string;
    pan_zoom_effect?: string;
    transition_to_next?: string;
  }[];

  // Narration TTS Audio (ElevenLabs / SpeechGen)
  narration?: {
    audio_path: string;
    start_time_offset: number;
  };

  // Subtitle Overlay
  subtitles?: {
    srt_path: string;
  };
}

