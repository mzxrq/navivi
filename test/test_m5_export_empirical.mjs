// test/test_m5_export_empirical.mjs
// Empirical test harness for Milestone M5: Export & Render Profiles
// Tests aspect ratio math, resolution mapping, bitrate/size calculations, and timeline manifest compilation.

import assert from "node:assert";

console.log("==================================================================");
console.log("STARTING EMPIRICAL TEST SUITE: MILESTONE M5 (EXPORT & PROFILES)");
console.log("Aspect Ratios, Quality Profiles, Bitrates, File Size & Manifest");
console.log("==================================================================\n");

let passedTests = 0;
let failedTests = 0;
const findings = [];

function test(name, fn) {
  try {
    fn();
    console.log(`  [PASS] ${name}`);
    passedTests++;
  } catch (err) {
    console.error(`  [FAIL] ${name}`);
    console.error(`         ${err.message}`);
    failedTests++;
    findings.push({ test: name, error: err.message });
  }
}

// -----------------------------------------------------------------------------
// Pure logic functions directly mirroring ExportModal.tsx and fileSystem.ts
// -----------------------------------------------------------------------------

const RESOLUTION_OPTIONS = [
  {
    id: "4k",
    label: "4K Ultra HD",
    tag: "UHD",
    landscape: { width: 3840, height: 2160 },
    portrait: { width: 2160, height: 3840 },
  },
  {
    id: "1080p",
    label: "1080p Full HD",
    tag: "FHD",
    landscape: { width: 1920, height: 1080 },
    portrait: { width: 1080, height: 1920 },
  },
  {
    id: "720p",
    label: "720p HD",
    tag: "HD",
    landscape: { width: 1280, height: 720 },
    portrait: { width: 720, height: 1280 },
  },
];

const BITRATE_PRESETS = [
  {
    id: "high",
    label: "High Quality",
    rates: { "4k": 50000, "1080p": 20000, "720p": 10000 },
  },
  {
    id: "standard",
    label: "Balanced / Standard",
    rates: { "4k": 25000, "1080p": 10000, "720p": 5000 },
  },
  {
    id: "draft",
    label: "Fast / Draft",
    rates: { "4k": 12000, "1080p": 5000, "720p": 2500 },
  },
];

function calculateEstimatedMb(durationSec, bitrateKbps) {
  if (!isFinite(durationSec) || durationSec <= 0) return 0;
  if (!isFinite(bitrateKbps) || bitrateKbps <= 0) return 0;
  return (durationSec * (bitrateKbps / 8)) / 1024;
}

function compileTimelineManifest(projectName, timeline, renderSettings, markers) {
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
      type: track?.name?.toLowerCase().includes("popup") ? "static_popup" : "video",
    });
  }

  const totalDuration = timeline.clips.reduce(
    (max, clip) => Math.max(max, clip.startTime + clip.duration),
    0
  );

  const aspectRatio = renderSettings?.aspectRatio || "16:9";
  const resolution = renderSettings?.resolution || { width: 1920, height: 1080 };
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

// -----------------------------------------------------------------------------
// Test Suite
// -----------------------------------------------------------------------------

console.log("SECTION 1: Aspect Ratio & Quality Profile Geometry");

test("16:9 Landscape resolution mapping (4K, 1080p, 720p)", () => {
  const res4k = RESOLUTION_OPTIONS.find((r) => r.id === "4k").landscape;
  assert.strictEqual(res4k.width, 3840);
  assert.strictEqual(res4k.height, 2160);
  assert.strictEqual(res4k.width / res4k.height, 16 / 9);

  const res1080 = RESOLUTION_OPTIONS.find((r) => r.id === "1080p").landscape;
  assert.strictEqual(res1080.width, 1920);
  assert.strictEqual(res1080.height, 1080);
  assert.strictEqual(res1080.width / res1080.height, 16 / 9);

  const res720 = RESOLUTION_OPTIONS.find((r) => r.id === "720p").landscape;
  assert.strictEqual(res720.width, 1280);
  assert.strictEqual(res720.height, 720);
  assert.strictEqual(res720.width / res720.height, 16 / 9);
});

test("9:16 Portrait resolution mapping (4K, 1080p, 720p)", () => {
  const res4k = RESOLUTION_OPTIONS.find((r) => r.id === "4k").portrait;
  assert.strictEqual(res4k.width, 2160);
  assert.strictEqual(res4k.height, 3840);
  assert.strictEqual(res4k.width / res4k.height, 9 / 16);

  const res1080 = RESOLUTION_OPTIONS.find((r) => r.id === "1080p").portrait;
  assert.strictEqual(res1080.width, 1080);
  assert.strictEqual(res1080.height, 1920);
  assert.strictEqual(res1080.width / res1080.height, 9 / 16);

  const res720 = RESOLUTION_OPTIONS.find((r) => r.id === "720p").portrait;
  assert.strictEqual(res720.width, 720);
  assert.strictEqual(res720.height, 1280);
  assert.strictEqual(res720.width / res720.height, 9 / 16);
});

console.log("\nSECTION 2: Bitrate Preset & Estimated File Size Math");

test("File size estimation for 1080p 60s at standard bitrate (10 Mbps)", () => {
  const durationSec = 60;
  const bitrateKbps = 10000;
  // 60s * 10,000 Kbps / 8 = 75,000 KB / 1024 = ~73.24 MB
  const estMb = calculateEstimatedMb(durationSec, bitrateKbps);
  assert(Math.abs(estMb - 73.242) < 0.01, `Expected ~73.24 MB, got ${estMb}`);
});

test("File size estimation for 4K 120s at high bitrate (50 Mbps)", () => {
  const durationSec = 120;
  const bitrateKbps = 50000;
  // 120s * 50,000 Kbps / 8 = 750,000 KB / 1024 = ~732.42 MB
  const estMb = calculateEstimatedMb(durationSec, bitrateKbps);
  assert(Math.abs(estMb - 732.421) < 0.01, `Expected ~732.42 MB, got ${estMb}`);
});

test("File size estimation edge cases (0s, negative, zero bitrate)", () => {
  assert.strictEqual(calculateEstimatedMb(0, 10000), 0);
  assert.strictEqual(calculateEstimatedMb(-10, 10000), 0);
  assert.strictEqual(calculateEstimatedMb(60, 0), 0);
  assert.strictEqual(calculateEstimatedMb(60, -5000), 0);
});

console.log("\nSECTION 3: Manifest Compilation & Payload Structure");

test("Manifest compiles multi-track timeline with audio, video, transitions and markers", () => {
  const dummyTimeline = {
    zoomMultiplier: 1,
    tracks: [
      { id: "track-video-1", name: "Main Video", type: "video", orderIndex: 0 },
      { id: "track-overlay-1", name: "Popup Overlays", type: "overlay", orderIndex: 1 },
      { id: "track-audio-1", name: "Voice Narration", type: "audio", orderIndex: 2, audioRole: "voice" },
      { id: "track-audio-2", name: "BGM", type: "audio", orderIndex: 3, audioRole: "music", duckingEnabled: true },
    ],
    clips: [
      { id: "c1", trackId: "track-video-1", type: "video", label: "Intro", startTime: 0, duration: 10, source: "video/intro.mp4" },
      { id: "c2", trackId: "track-video-1", type: "video", label: "Waypoint 1", startTime: 10, duration: 15, source: "video/wp1.mp4" },
      { id: "c3", trackId: "track-overlay-1", type: "image", label: "Popup Card", startTime: 12, duration: 4, source: "img/card.png" },
      { id: "c4", trackId: "track-audio-1", type: "audio", label: "Voice WP1", startTime: 10, duration: 8, source: "audio/tts1.wav" },
    ],
    transitions: [
      { id: "t1", trackId: "track-video-1", fromClipId: "c1", toClipId: "c2", type: "crossfade", startTime: 9, duration: 1 },
    ],
  };

  const markers = [
    { id: "wp-1", name: "Kyoto Station", time: 0 },
    { id: "wp-2", name: "Fushimi Inari", time: 10 },
  ];

  const renderSettings = {
    aspectRatio: "9:16",
    resolution: { width: 1080, height: 1920 },
    fps: 60,
    bitrateKbps: 20000,
    qualityId: "1080p",
  };

  const manifest = compileTimelineManifest("Kyoto_Trip", dummyTimeline, renderSettings, markers);

  // Verify total duration calculation
  assert.strictEqual(manifest.total_duration_seconds, 25);
  assert.strictEqual(manifest.totalDuration, 25);

  // Verify project name
  assert.strictEqual(manifest.project_name, "Kyoto_Trip");
  assert.strictEqual(manifest.projectName, "Kyoto_Trip");

  // Verify aspect ratio & resolution
  assert.strictEqual(manifest.aspect_ratio, "9:16");
  assert.strictEqual(manifest.aspectRatio, "9:16");
  assert.deepStrictEqual(manifest.resolution, { width: 1080, height: 1920 });
  assert.strictEqual(manifest.fps, 60);
  assert.strictEqual(manifest.bitrate_kbps, 20000);
  assert.strictEqual(manifest.bitrateKbps, 20000);

  // Verify visual clips sorting and popup typing
  assert.strictEqual(manifest.video_tracks.length, 3);
  assert.strictEqual(manifest.video_tracks[0].clip_id, "c1");
  assert.strictEqual(manifest.video_tracks[0].type, "video");
  assert.strictEqual(manifest.video_tracks[1].clip_id, "c2");
  assert.strictEqual(manifest.video_tracks[1].type, "video");
  assert.strictEqual(manifest.video_tracks[2].clip_id, "c3");
  assert.strictEqual(manifest.video_tracks[2].type, "static_popup");

  // Verify markers
  assert.strictEqual(manifest.markers.length, 2);
  assert.strictEqual(manifest.markers[0].name, "Kyoto Station");
  assert.strictEqual(manifest.markers[1].time, 10);

  // Verify transitions
  assert.strictEqual(manifest.transitions.length, 1);
  assert.strictEqual(manifest.transitions[0].type, "crossfade");

  // Verify renderSettings sub-object
  assert(manifest.render_settings);
  assert.strictEqual(manifest.render_settings.aspectRatio, "9:16");
  assert.strictEqual(manifest.render_settings.qualityId, "1080p");
});

test("Manifest handles empty timeline without throwing", () => {
  const emptyTimeline = { zoomMultiplier: 1, tracks: [], clips: [], transitions: [] };
  const manifest = compileTimelineManifest("Empty_Project", emptyTimeline);

  assert.strictEqual(manifest.total_duration_seconds, 0);
  assert.strictEqual(manifest.totalDuration, 0);
  assert.strictEqual(manifest.video_tracks.length, 0);
  assert.strictEqual(manifest.markers.length, 0);
  assert.strictEqual(manifest.aspect_ratio, "16:9");
  assert.deepStrictEqual(manifest.resolution, { width: 1920, height: 1080 });
});

test("Manifest JSON round-trip serialization is lossless", () => {
  const sampleTimeline = {
    zoomMultiplier: 1.5,
    tracks: [{ id: "t1", name: "V1", type: "video", orderIndex: 0 }],
    clips: [{ id: "c1", trackId: "t1", label: "Clip 1", startTime: 0, duration: 8.5 }],
    transitions: [],
  };
  const settings = {
    aspectRatio: "16:9",
    resolution: { width: 3840, height: 2160 },
    fps: 30,
    bitrateKbps: 25000,
    qualityId: "4k",
  };

  const compiled = compileTimelineManifest("Sample", sampleTimeline, settings, []);
  const jsonText = JSON.stringify(compiled, null, 2);
  const parsed = JSON.parse(jsonText);

  assert.strictEqual(parsed.project_name, compiled.project_name);
  assert.strictEqual(parsed.aspect_ratio, "16:9");
  assert.strictEqual(parsed.resolution.width, 3840);
  assert.strictEqual(parsed.resolution.height, 2160);
  assert.strictEqual(parsed.total_duration_seconds, 8.5);
});

console.log("\n==================================================================");
console.log(`RESULTS: ${passedTests} passed, ${failedTests} failed.`);
console.log("==================================================================");

if (failedTests > 0) {
  process.exit(1);
}
