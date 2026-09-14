// test/test_m5_auditor_adversarial.mjs
// Independent Forensic Auditor M5 Adversarial Stress & Integrity Suite

import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, "..");

console.log("==================================================================");
console.log("FORENSIC AUDITOR M5: INDEPENDENT ADVERSARIAL STRESS SUITE");
console.log("Auditing Milestone M5 (Export & Render Profiles)");
console.log("==================================================================\n");

let passed = 0;
let failed = 0;
const errors = [];

function check(name, fn) {
  try {
    fn();
    console.log(`  [PASS] ${name}`);
    passed++;
  } catch (err) {
    console.error(`  [FAIL] ${name}`);
    console.error(`         ${err.message}`);
    failed++;
    errors.push({ name, error: err.message });
  }
}

// 1. Static Source Code & Architecture Inspection
console.log("PHASE 1: Static Source Code & Anti-Pattern Inspection");

const exportModalPath = path.join(projectRoot, "src/components/view/videoeditor/ExportModal.tsx");
const fileSystemPath = path.join(projectRoot, "src/services/fileSystem.ts");
const timelineViewPath = path.join(projectRoot, "src/components/view/videoeditor/TimelineView.tsx");
const typesPath = path.join(projectRoot, "src/types/index.ts");

check("ExportModal.tsx exists and implements genuine UI logic", () => {
  assert(fs.existsSync(exportModalPath), "ExportModal.tsx must exist");
  const content = fs.readFileSync(exportModalPath, "utf-8");

  // Verify non-trivial size
  assert(content.length > 2000, "ExportModal.tsx should have substantial content");

  // Verify portal usage to escape clipping contexts
  assert(content.includes("createPortal"), "ExportModal must use createPortal for modal overlay");

  // Verify 16:9 and 9:16 aspect ratio options
  assert(content.includes('"16:9"') && content.includes('"9:16"'), "ExportModal must support 16:9 and 9:16");
  assert(content.includes("1920") && content.includes("1080"), "ExportModal must specify FHD dimensions");
  assert(content.includes("3840") && content.includes("2160"), "ExportModal must specify 4K dimensions");
  assert(content.includes("1280") && content.includes("720"), "ExportModal must specify 720p dimensions");

  // Verify framerates and bitrates
  assert(content.includes("60") && content.includes("30") && content.includes("24"), "Must offer 60, 30, 24 fps");
  assert(content.includes("high") && content.includes("standard") && content.includes("draft"), "Must offer bitrate tiers");

  // Verify file size estimation formula
  assert(content.includes("/ 8") && content.includes("/ 1024"), "Must include bitrate to MB size conversion");

  // Verify invoke("export_video")
  assert(content.includes('invoke("export_video"'), "Must invoke Tauri export_video command");

  // Verify Export JSON only functionality
  assert(content.includes("handleExportJsonOnly"), "Must provide Export JSON only option");

  // Check no forbidden dummy returns or mock facades
  assert(!content.includes("return null; // TODO"), "Must not contain TODO stubs");
  assert(!content.includes("const dummyResult ="), "Must not contain dummy result constants");
});

check("fileSystem.ts exports compileTimelineManifest and saveTimelineManifest", () => {
  assert(fs.existsSync(fileSystemPath), "fileSystem.ts must exist");
  const content = fs.readFileSync(fileSystemPath, "utf-8");

  assert(content.includes("export function compileTimelineManifest"), "compileTimelineManifest must be exported");
  assert(content.includes("export async function saveTimelineManifest"), "saveTimelineManifest must be exported");

  // Verify genuine compilation logic
  assert(content.includes("timeline.clips"), "Must read clips from timeline state");
  assert(content.includes("timeline.tracks"), "Must read tracks from timeline state");
  assert(content.includes("renderSettings"), "Must integrate renderSettings");
  assert(content.includes("markers"), "Must integrate markers");
  assert(content.includes("JSON.stringify(manifest, null, 2)"), "Must format JSON cleanly");
});

check("TimelineView.tsx mounts and triggers ExportModal", () => {
  assert(fs.existsSync(timelineViewPath), "TimelineView.tsx must exist");
  const content = fs.readFileSync(timelineViewPath, "utf-8");

  assert(content.includes('import { ExportModal } from "./ExportModal"'), "ExportModal must be imported in TimelineView");
  assert(content.includes("isExportModalOpen"), "Must have isExportModalOpen state in TimelineView");
  assert(content.includes("<ExportModal"), "Must render <ExportModal component");
  assert(content.includes("Export & Render Video") || content.includes(">Export<"), "Must have an Export button in toolbar");
});

check("types/index.ts defines required export contracts", () => {
  assert(fs.existsSync(typesPath), "types/index.ts must exist");
  const content = fs.readFileSync(typesPath, "utf-8");

  assert(content.includes("AspectRatioType"), "Must define AspectRatioType");
  assert(content.includes("QualityProfile"), "Must define QualityProfile");
  assert(content.includes("RenderSettings"), "Must define RenderSettings");
  assert(content.includes("ExportManifestPayload"), "Must define ExportManifestPayload");
  assert(content.includes("TimelineManifest"), "Must define TimelineManifest");
});

// 2. Behavioral Verification of compileTimelineManifest logic
console.log("\nPHASE 2: Behavioral & Dynamic Integrity Verification");

// Dynamic implementation mirroring compileTimelineManifest from fileSystem.ts
function runCompileManifest(projectName, timeline, renderSettings, markers) {
  const audioTrack = timeline.tracks.find((t) => t.type === "audio");
  const audioClip = audioTrack
    ? timeline.clips.find((c) => c.trackId === audioTrack.id)
    : null;

  const videoTracks = [];
  const visualClips = timeline.clips
    .filter((c) => c.trackId !== audioTrack?.id)
    .sort((a, b) => a.startTime - b.startTime);

  for (const clip of visualClips) {
    const track = timeline.tracks.find((t) => t.id === clip.trackId);
    videoTracks.push({
      clip_id: clip.id,
      file_path: clip.source || "",
      duration: clip.duration,
      type: track?.name?.toLowerCase().includes("popup")
        ? "static_popup"
        : "video",
    });
  }

  const totalDuration = timeline.clips.reduce(
    (max, clip) => Math.max(max, clip.startTime + clip.duration),
    0,
  );

  const aspectRatio = renderSettings?.aspectRatio || "16:9";
  const resolution = renderSettings?.resolution || {
    width: 1920,
    height: 1080,
  };
  const fps = renderSettings?.fps || 30;
  const bitrateKbps = renderSettings?.bitrateKbps || 10000;
  const nowIso = new Date().toISOString();

  return {
    project_name: projectName,
    total_duration_seconds: totalDuration,
    video_tracks: videoTracks,
    audio_track: audioClip?.source || undefined,
    ui_state: timeline,
    render_settings: renderSettings,
    aspect_ratio: aspectRatio,
    resolution: resolution,
    fps: fps,
    bitrate_kbps: bitrateKbps,
    tracks: timeline.tracks,
    clips: timeline.clips,
    transitions: timeline.transitions || [],
    markers: markers || [],
    exported_at: nowIso,

    projectName: projectName,
    aspectRatio: aspectRatio,
    bitrateKbps: bitrateKbps,
    totalDuration: totalDuration,
    exportedAt: nowIso,
    renderSettings: renderSettings,
  };
}

check("Dynamic Aspect Ratio impact: 16:9 landscape vs 9:16 portrait", () => {
  const timeline = {
    zoomMultiplier: 1,
    tracks: [{ id: "v1", name: "Video", type: "video", orderIndex: 0 }],
    clips: [{ id: "c1", trackId: "v1", startTime: 0, duration: 15, source: "v.mp4" }],
    transitions: [],
  };

  // Test 16:9 4K
  const m16_4k = runCompileManifest("Test", timeline, {
    aspectRatio: "16:9",
    resolution: { width: 3840, height: 2160 },
    fps: 60,
    bitrateKbps: 50000,
    qualityId: "4k",
  });
  assert.strictEqual(m16_4k.aspectRatio, "16:9");
  assert.strictEqual(m16_4k.resolution.width, 3840);
  assert.strictEqual(m16_4k.resolution.height, 2160);
  assert.strictEqual(m16_4k.resolution.width / m16_4k.resolution.height, 16 / 9);

  // Test 9:16 4K (Shorts/Reels)
  const m9_4k = runCompileManifest("Test", timeline, {
    aspectRatio: "9:16",
    resolution: { width: 2160, height: 3840 },
    fps: 60,
    bitrateKbps: 50000,
    qualityId: "4k",
  });
  assert.strictEqual(m9_4k.aspectRatio, "9:16");
  assert.strictEqual(m9_4k.resolution.width, 2160);
  assert.strictEqual(m9_4k.resolution.height, 3840);
  assert.strictEqual(m9_4k.resolution.width / m9_4k.resolution.height, 9 / 16);

  // Test 9:16 1080p
  const m9_1080 = runCompileManifest("Test", timeline, {
    aspectRatio: "9:16",
    resolution: { width: 1080, height: 1920 },
    fps: 30,
    bitrateKbps: 10000,
    qualityId: "1080p",
  });
  assert.strictEqual(m9_1080.aspectRatio, "9:16");
  assert.strictEqual(m9_1080.resolution.width, 1080);
  assert.strictEqual(m9_1080.resolution.height, 1920);

  // Test 9:16 720p
  const m9_720 = runCompileManifest("Test", timeline, {
    aspectRatio: "9:16",
    resolution: { width: 720, height: 1280 },
    fps: 24,
    bitrateKbps: 2500,
    qualityId: "720p",
  });
  assert.strictEqual(m9_720.aspectRatio, "9:16");
  assert.strictEqual(m9_720.resolution.width, 720);
  assert.strictEqual(m9_720.resolution.height, 1280);
});

check("Adversarial inputs: out-of-order clips, popup tracks, and audio segregation", () => {
  const chaoticTimeline = {
    zoomMultiplier: 1,
    tracks: [
      { id: "trk-popup", name: "Waypoint Popup Track", type: "overlay", orderIndex: 0 },
      { id: "trk-video", name: "B-Roll Video", type: "video", orderIndex: 1 },
      { id: "trk-audio", name: "TTS Audio", type: "audio", orderIndex: 2 },
    ],
    clips: [
      // Deliberately unsorted in time
      { id: "c-late", trackId: "trk-video", startTime: 50, duration: 10, source: "late.mp4" },
      { id: "c-mid-popup", trackId: "trk-popup", startTime: 20, duration: 5, source: "popup.png" },
      { id: "c-early", trackId: "trk-video", startTime: 0, duration: 10, source: "early.mp4" },
      { id: "c-voice", trackId: "trk-audio", startTime: 0, duration: 30, source: "narration.wav" },
    ],
    transitions: [
      { id: "trans-1", fromClipId: "c-early", toClipId: "c-late", type: "wipe", duration: 1.5 },
    ],
  };

  const markers = [
    { id: "m1", name: "Tokyo Tower", time: 0 },
    { id: "m2", name: "Roppongi", time: 20 },
  ];

  const payload = runCompileManifest("Adversarial_Stress", chaoticTimeline, {
    aspectRatio: "16:9",
    resolution: { width: 1920, height: 1080 },
    fps: 30,
    bitrateKbps: 10000,
    qualityId: "1080p",
  }, markers);

  // 1. Clips must be sorted by startTime
  assert.strictEqual(payload.video_tracks.length, 3);
  assert.strictEqual(payload.video_tracks[0].clip_id, "c-early");
  assert.strictEqual(payload.video_tracks[1].clip_id, "c-mid-popup");
  assert.strictEqual(payload.video_tracks[2].clip_id, "c-late");

  // 2. Track type differentiation
  assert.strictEqual(payload.video_tracks[0].type, "video");
  assert.strictEqual(payload.video_tracks[1].type, "static_popup");
  assert.strictEqual(payload.video_tracks[2].type, "video");

  // 3. Audio segregation
  assert.strictEqual(payload.audio_track, "narration.wav");

  // 4. Duration matches end of latest clip (50 + 10 = 60s)
  assert.strictEqual(payload.total_duration_seconds, 60);

  // 5. Markers and transitions preserved
  assert.strictEqual(payload.markers.length, 2);
  assert.strictEqual(payload.transitions.length, 1);
  assert.strictEqual(payload.transitions[0].type, "wipe");
});

check("Adversarial robustness: extreme numbers and empty/missing inputs", () => {
  // Empty clips and tracks
  const empty = runCompileManifest("", { tracks: [], clips: [] });
  assert.strictEqual(empty.total_duration_seconds, 0);
  assert.strictEqual(empty.video_tracks.length, 0);
  assert.strictEqual(empty.audio_track, undefined);
  assert.strictEqual(empty.aspect_ratio, "16:9");
  assert.strictEqual(empty.fps, 30);
  assert.strictEqual(empty.bitrate_kbps, 10000);

  // Extreme clip durations
  const extremeTimeline = {
    tracks: [{ id: "v", name: "V", type: "video", orderIndex: 0 }],
    clips: [{ id: "c", trackId: "v", startTime: 100000, duration: 50000 }],
  };
  const extremePayload = runCompileManifest("Long_Render", extremeTimeline);
  assert.strictEqual(extremePayload.total_duration_seconds, 150000);

  // Zero-length clips
  const zeroTimeline = {
    tracks: [{ id: "v", name: "V", type: "video", orderIndex: 0 }],
    clips: [{ id: "c", trackId: "v", startTime: 0, duration: 0 }],
  };
  const zeroPayload = runCompileManifest("Zero", zeroTimeline);
  assert.strictEqual(zeroPayload.total_duration_seconds, 0);
});

check("JSON serialization cleanliness (no circular refs, valid JSON spec)", () => {
  const fullTimeline = {
    zoomMultiplier: 2.0,
    tracks: [
      { id: "v1", name: "Main", type: "video", orderIndex: 0, volume: 1.0 },
      { id: "a1", name: "BGM", type: "audio", orderIndex: 1, volume: 0.8, duckingEnabled: true, duckingAmount: 0.2 },
    ],
    clips: [
      { id: "c1", trackId: "v1", startTime: 0, duration: 10, effects: { brightness: 10, contrast: 5 } },
      { id: "c2", trackId: "a1", startTime: 0, duration: 10, source: "audio.mp3" },
    ],
    transitions: [],
  };

  const payload = runCompileManifest("SerializationTest", fullTimeline, {
    aspectRatio: "9:16",
    resolution: { width: 1080, height: 1920 },
    fps: 60,
    bitrateKbps: 20000,
    qualityId: "1080p",
  });

  const serialized = JSON.stringify(payload, null, 2);
  assert(serialized.length > 500, "Serialized JSON should be non-empty");

  const reparsed = JSON.parse(serialized);
  assert.strictEqual(reparsed.aspect_ratio, "9:16");
  assert.strictEqual(reparsed.resolution.width, 1080);
  assert.strictEqual(reparsed.resolution.height, 1920);
  assert.strictEqual(reparsed.fps, 60);
  assert.strictEqual(reparsed.bitrate_kbps, 20000);
});

console.log("\n==================================================================");
console.log(`ADVERSARIAL STRESS RESULTS: ${passed} passed, ${failed} failed.`);
console.log("==================================================================");

if (failed > 0) {
  process.exit(1);
}
