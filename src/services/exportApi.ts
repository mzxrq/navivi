import { Waypoint, ProjectSettings } from "../types";
import { fetch } from "@tauri-apps/plugin-http";

export interface ExportPayload {
  settings: ProjectSettings;
  clips: any[];
}

export async function exportVideo(waypoints: Waypoint[], settings: ProjectSettings): Promise<any> {
  let runningTime = 0;
  
  const blocks = waypoints.map((wp) => {
    const duration = 5; // Default 5s
    const startTime = wp.timelineOffset !== undefined ? wp.timelineOffset : runningTime;
    
    // Auto-advance for the next sequence if it hasn't been manually moved too far
    runningTime = Math.max(runningTime, startTime + duration);
    
    return {
      id: wp.id,
      name: wp.name || "Waypoint",
      startTime,
      duration,
      trackIndex: 0,
      wp
    };
  });

  const allClips: any[] = [];
  
  blocks.forEach(b => {
    // Flight block
    allClips.push({
      ...b,
      label: `Route to ${b.name}`,
      color: "#0284c7",
      type: "flight"
    });
    
    // Video block
    if (b.wp.videoUrl || b.wp.isGeneratingVideo || b.wp.videoPrompt) {
      allClips.push({
        id: b.id + "-video",
        name: "Wan 2.2 Video",
        label: "Video",
        startTime: b.wp.videoOffset !== undefined ? b.wp.videoOffset : b.startTime,
        duration: b.duration,
        trackIndex: 1,
        color: "#16a34a",
        wp: b.wp,
        type: "video"
      });
    }

    // Audio block
    if (b.wp.audioUrl || b.wp.isGeneratingAudio || b.wp.narration || b.wp.arrivingNarration || b.wp.attractionNarration) {
      allClips.push({
        id: b.id + "-audio",
        name: "Irodori Audio",
        label: "Audio",
        startTime: b.wp.audioOffset !== undefined ? b.wp.audioOffset : b.startTime,
        duration: b.duration,
        trackIndex: 2,
        color: "#ea580c",
        wp: b.wp,
        type: "audio"
      });
    }
  });

  const payload: ExportPayload = {
    settings,
    clips: allClips,
  };

  const response = await fetch("http://127.0.0.1:8000/api/render", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    throw new Error(`Failed to export video: ${response.statusText}`);
  }

  return response.json();
}
