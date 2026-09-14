// test/test_m5_adversarial_stress.mjs
// Adversarial Stress Test Suite: Milestone M5 (Export & Render Profiles)
// Authored by Challenger M5-1
// Stress-tests aspect ratio geometry, resolution toggling, bitrate math,
// duration boundaries, missing metadata, and manifest compilation edge cases.

import assert from "node:assert";

console.log("======================================================================");
console.log("CHALLENGER M5-1: ADVERSARIAL STRESS TEST HARNESS");
console.log("Milestone M5 — Aspect Ratio Geometry, Bitrates & Export Manifest");
console.log("======================================================================\n");

let passed = 0;
let failed = 0;
const failures = [];
const anomalies = [];

function challenge(name, fn) {
  try {
    fn();
    console.log(`  [PASS] ${name}`);
    passed++;
  } catch (err) {
    console.error(`  [FAIL] ${name}`);
    console.error(`         Reason: ${err.message}`);
    failed++;
    failures.push({ name, error: err.message });
  }
}

function noteAnomaly(name, detail) {
  console.log(`  [ANOMALY DETECTED] ${name}: ${detail}`);
  anomalies.push({ name, detail });
}

// -----------------------------------------------------------------------------
// Reference constants and logic directly from ExportModal.tsx & fileSystem.ts
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
    description: "Maximum quality for archival and master presentation (50 Mbps 4K / 20 Mbps 1080p)",
    rates: {
      "4k": 50000,
      "1080p": 20000,
      "720p": 10000,
    },
  },
  {
    id: "standard",
    label: "Balanced / Standard",
    description: "Optimal balance between quality and file size for web & YouTube (25 Mbps 4K / 10 Mbps 1080p)",
    rates: {
      "4k": 25000,
      "1080p": 10000,
      "720p": 5000,
    },
  },
  {
    id: "draft",
    label: "Fast / Draft",
    description: "Fastest export with compact file size for quick previews (12 Mbps 4K / 5 Mbps 1080p)",
    rates: {
      "4k": 12000,
      "1080p": 5000,
      "720p": 2500,
    },
  },
];

// Calculation functions from ExportModal.tsx
function computeActiveDimensions(aspectRatio, resolutionTier) {
  const option = RESOLUTION_OPTIONS.find((r) => r.id === resolutionTier) || RESOLUTION_OPTIONS[1];
  return aspectRatio === "16:9" ? option.landscape : option.portrait;
}

function computeActiveBitrateKbps(bitrateTier, resolutionTier) {
  const preset = BITRATE_PRESETS.find((b) => b.id === bitrateTier) || BITRATE_PRESETS[1];
  return preset.rates[resolutionTier];
}

function computeTotalDuration(duration, clips) {
  if (typeof duration === "number" && duration > 0) return duration;
  return (clips || []).reduce(
    (max, clip) => Math.max(max, clip.startTime + clip.duration),
    0
  );
}

function computeEstimatedMb(totalDuration, activeBitrateKbps) {
  return (totalDuration * (activeBitrateKbps / 8)) / 1024;
}

function formatEstimatedSize(estimatedMb) {
  if (estimatedMb >= 1024) {
    return `${(estimatedMb / 1024).toFixed(2)} GB`;
  }
  return `${Math.max(0.1, estimatedMb).toFixed(1)} MB`;
}

function formatTime(seconds) {
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

// Markers calculation from ExportModal.tsx
function computeMarkers(waypoints) {
  if (!waypoints || waypoints.length === 0) return [];
  let runningTime = 0;
  return waypoints.map((wp, idx) => {
    const legDuration = 5;
    const time = wp.timelineOffset !== undefined ? wp.timelineOffset : runningTime;
    runningTime = Math.max(runningTime, time + legDuration);
    return {
      id: wp.id,
      name: wp.name || `Waypoint ${idx + 1}`,
      time,
      index: idx,
    };
  });
}

// Manifest compilation from fileSystem.ts
function compileTimelineManifestProduction(projectName, timeline, renderSettings, markers) {
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
      // EXACT verbatim implementation from src/services/fileSystem.ts line 294:
      type: track?.name.toLowerCase().includes("popup")
        ? "static_popup"
        : "video",
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
// CHALLENGE 1: Aspect Ratio Geometry & Symmetry Across All Tiers
// -----------------------------------------------------------------------------
console.log("\n--- CHALLENGE 1: Aspect Ratio Geometry & Symmetry Across Tiers ---");

challenge("Aspect ratio geometry toggle 16:9 <-> 9:16 across 4K, 1080p, 720p", () => {
  const tiers = ["4k", "1080p", "720p"];
  for (const tier of tiers) {
    const landscape = computeActiveDimensions("16:9", tier);
    const portrait = computeActiveDimensions("9:16", tier);

    // Inversion symmetry
    assert.strictEqual(landscape.width, portrait.height, `Inversion mismatch width->height for tier ${tier}`);
    assert.strictEqual(landscape.height, portrait.width, `Inversion mismatch height->width for tier ${tier}`);

    // Exact mathematical ratios
    const landscapeRatio = landscape.width / landscape.height;
    const portraitRatio = portrait.width / portrait.height;
    assert(Math.abs(landscapeRatio - 16 / 9) < 1e-6, `Landscape ratio not 16:9 for ${tier}: got ${landscapeRatio}`);
    assert(Math.abs(portraitRatio - 9 / 16) < 1e-6, `Portrait ratio not 9:16 for ${tier}: got ${portraitRatio}`);

    // Codec alignment: even dimensions for H.264/H.265 (mod 2 == 0)
    assert.strictEqual(landscape.width % 2, 0, `Landscape width not even for ${tier}`);
    assert.strictEqual(landscape.height % 2, 0, `Landscape height not even for ${tier}`);
    assert.strictEqual(portrait.width % 2, 0, `Portrait width not even for ${tier}`);
    assert.strictEqual(portrait.height % 2, 0, `Portrait height not even for ${tier}`);
  }
});

challenge("State persistence during aspect ratio and resolution toggling sequence", () => {
  // Simulate user workflow:
  // 1. Start at 1080p 16:9
  let aspect = "16:9";
  let tier = "1080p";
  let dims = computeActiveDimensions(aspect, tier);
  assert.deepStrictEqual(dims, { width: 1920, height: 1080 });

  // 2. User switches to 4K
  tier = "4k";
  dims = computeActiveDimensions(aspect, tier);
  assert.deepStrictEqual(dims, { width: 3840, height: 2160 });

  // 3. User switches to 9:16 Shorts
  aspect = "9:16";
  dims = computeActiveDimensions(aspect, tier);
  assert.deepStrictEqual(dims, { width: 2160, height: 3840 });

  // 4. User switches to 720p in 9:16
  tier = "720p";
  dims = computeActiveDimensions(aspect, tier);
  assert.deepStrictEqual(dims, { width: 720, height: 1280 });

  // 5. User switches back to 16:9
  aspect = "16:9";
  dims = computeActiveDimensions(aspect, tier);
  assert.deepStrictEqual(dims, { width: 1280, height: 720 });
});

challenge("Invalid or unknown resolution tier falls back safely to 1080p", () => {
  const invalidTier = "8k_unknown";
  const dimsLandscape = computeActiveDimensions("16:9", invalidTier);
  assert.deepStrictEqual(dimsLandscape, { width: 1920, height: 1080 });

  const dimsPortrait = computeActiveDimensions("9:16", invalidTier);
  assert.deepStrictEqual(dimsPortrait, { width: 1080, height: 1920 });
});

// -----------------------------------------------------------------------------
// CHALLENGE 2: Bitrate Preset Monotonicity and Calculations
// -----------------------------------------------------------------------------
console.log("\n--- CHALLENGE 2: Bitrate Preset Monotonicity & Rates ---");

challenge("Bitrate preset ordering: High > Standard > Draft for every resolution", () => {
  const tiers = ["4k", "1080p", "720p"];
  for (const tier of tiers) {
    const high = computeActiveBitrateKbps("high", tier);
    const standard = computeActiveBitrateKbps("standard", tier);
    const draft = computeActiveBitrateKbps("draft", tier);

    assert(high > standard, `Expected high > standard for ${tier}: ${high} vs ${standard}`);
    assert(standard > draft, `Expected standard > draft for ${tier}: ${standard} vs ${draft}`);
  }
});

challenge("Resolution bitrate ordering: 4K > 1080p > 720p for every quality preset", () => {
  const presets = ["high", "standard", "draft"];
  for (const preset of presets) {
    const r4k = computeActiveBitrateKbps(preset, "4k");
    const r1080 = computeActiveBitrateKbps(preset, "1080p");
    const r720 = computeActiveBitrateKbps(preset, "720p");

    assert(r4k > r1080, `Expected 4k > 1080p for ${preset}: ${r4k} vs ${r1080}`);
    assert(r1080 > r720, `Expected 1080p > 720p for ${preset}: ${r1080} vs ${r720}`);
  }
});

// -----------------------------------------------------------------------------
// CHALLENGE 3: File Size Estimation Math & Duration Boundaries
// -----------------------------------------------------------------------------
console.log("\n--- CHALLENGE 3: File Size Estimation Math & Boundaries ---");

challenge("File size for zero duration (0s)", () => {
  const mb = computeEstimatedMb(0, 10000);
  assert.strictEqual(mb, 0);
  const formatted = formatEstimatedSize(mb);
  // Note: formatEstimatedSize uses Math.max(0.1, estimatedMb).toFixed(1)
  // When estimatedMb is 0, this outputs "0.1 MB"
  assert.strictEqual(formatted, "0.1 MB");
  noteAnomaly("Zero duration file size format", `0 seconds outputs "${formatted}" due to Math.max(0.1, ...) clamping`);
});

challenge("File size for negative duration (-30s)", () => {
  // computeTotalDuration with negative duration param
  const duration = computeTotalDuration(-30, []);
  assert.strictEqual(duration, 0, "Negative duration parameter should sanitize to 0");
  const mb = computeEstimatedMb(duration, 10000);
  assert.strictEqual(mb, 0);
  assert.strictEqual(formatEstimatedSize(mb), "0.1 MB");
});

challenge("File size for fractional duration (0.001s, 0.5s, 14.333s)", () => {
  // 0.5s at 10,000 Kbps = 0.5 * 1250 / 1024 = 0.61035 MB
  const mb05 = computeEstimatedMb(0.5, 10000);
  assert(Math.abs(mb05 - 0.61035) < 0.001);
  assert.strictEqual(formatEstimatedSize(mb05), "0.6 MB");

  // 1ms (0.001s) at 10,000 Kbps = 0.00122 MB -> clamped to 0.1 MB
  const mb1ms = computeEstimatedMb(0.001, 10000);
  assert.strictEqual(formatEstimatedSize(mb1ms), "0.1 MB");

  // 14.333s at 20,000 Kbps (1080p High) = 14.333 * 2500 / 1024 = 34.9926 MB
  const mb14 = computeEstimatedMb(14.333, 20000);
  assert(Math.abs(mb14 - 34.9926) < 0.01);
  assert.strictEqual(formatEstimatedSize(mb14), "35.0 MB");
});

challenge("File size for extreme duration: 1 hour, 10 hours, 24 hours", () => {
  // 1 hour (3600s) at 1080p standard (10,000 Kbps)
  const mb1h = computeEstimatedMb(3600, 10000);
  // 3600 * 1250 / 1024 = 4394.53125 MB -> 4.29 GB
  assert(Math.abs(mb1h - 4394.53) < 0.01);
  assert.strictEqual(formatEstimatedSize(mb1h), "4.29 GB");

  // 10 hours (36000s) at 4K High (50,000 Kbps)
  const mb10h = computeEstimatedMb(36000, 50000);
  // 36000 * (50000/8) / 1024 = 219726.5625 MB -> 214.58 GB
  assert(Math.abs(mb10h - 219726.56) < 0.01);
  assert.strictEqual(formatEstimatedSize(mb10h), "214.58 GB");

  // 24 hours (86400s) at 4K High (50,000 Kbps)
  const mb24h = computeEstimatedMb(86400, 50000);
  // 86400 * 6250 / 1024 = 527343.75 MB -> 514.98 GB
  assert(Math.abs(mb24h - 527343.75) < 0.01);
  assert.strictEqual(formatEstimatedSize(mb24h), "514.98 GB");
});

challenge("1024 MB boundary precision test", () => {
  // Exactly 1023.99 MB -> should display in MB
  const formattedBelow = formatEstimatedSize(1023.99);
  assert.strictEqual(formattedBelow, "1024.0 MB");

  // Exactly 1024.00 MB -> should transition to GB
  const formattedAt = formatEstimatedSize(1024.0);
  assert.strictEqual(formattedAt, "1.00 GB");

  // 2048 MB -> exactly 2.00 GB
  const formatted2g = formatEstimatedSize(2048.0);
  assert.strictEqual(formatted2g, "2.00 GB");
});

// -----------------------------------------------------------------------------
// CHALLENGE 4: Time Formatting Math & Edge Cases
// -----------------------------------------------------------------------------
console.log("\n--- CHALLENGE 4: Time Formatting Math ---");

challenge("Time formatting across 0s, seconds, minutes, and extreme hours", () => {
  assert.strictEqual(formatTime(0), "00:00");
  assert.strictEqual(formatTime(9), "00:09");
  assert.strictEqual(formatTime(59), "00:59");
  assert.strictEqual(formatTime(60), "01:00");
  assert.strictEqual(formatTime(125), "02:05");
  assert.strictEqual(formatTime(3599), "59:59");
  assert.strictEqual(formatTime(3600), "60:00"); // 1 hour = 60 minutes
  assert.strictEqual(formatTime(36000), "600:00"); // 10 hours = 600 minutes
});

challenge("Fractional seconds floor truncation in time formatting", () => {
  assert.strictEqual(formatTime(10.999), "00:10");
  assert.strictEqual(formatTime(65.4), "01:05");
});

// -----------------------------------------------------------------------------
// CHALLENGE 5: Timeline Duration Reduction Logic & Clip Overlaps
// -----------------------------------------------------------------------------
console.log("\n--- CHALLENGE 5: Timeline Duration & Clip Overlaps ---");

challenge("Duration calculation with multiple overlapping, out-of-order, and gap clips", () => {
  const clips = [
    { startTime: 30, duration: 10 },  // ends at 40
    { startTime: 0, duration: 25 },   // ends at 25
    { startTime: 50, duration: 15 },  // ends at 65 (max)
    { startTime: 10, duration: 5 },   // ends at 15
  ];
  const duration = computeTotalDuration(undefined, clips);
  assert.strictEqual(duration, 65);
});

challenge("Duration calculation ignores negative clips and defaults to 0", () => {
  const clipsWithNegative = [
    { startTime: -10, duration: 5 }, // ends at -5
    { startTime: -20, duration: -5 }, // ends at -25
  ];
  const duration = computeTotalDuration(undefined, clipsWithNegative);
  assert.strictEqual(duration, 0, "Should clamp at 0");
});

// -----------------------------------------------------------------------------
// CHALLENGE 6: Waypoint Sync Markers Calculation
// -----------------------------------------------------------------------------
console.log("\n--- CHALLENGE 6: Waypoint Sync Markers Calculation ---");

challenge("Waypoints with explicit timelineOffset vs default 5s cadence", () => {
  const waypoints = [
    { id: "wp1", name: "Tokyo", timelineOffset: 0 },
    { id: "wp2", name: "Nagoya", timelineOffset: 12.5 },
    { id: "wp3", name: "Kyoto" }, // missing offset -> should take Nagoya (12.5) + legDuration (5) = 17.5
    { id: "wp4" }, // missing name and offset -> should take 17.5 + 5 = 22.5, name "Waypoint 4"
  ];
  const markers = computeMarkers(waypoints);

  assert.strictEqual(markers.length, 4);
  assert.strictEqual(markers[0].time, 0);
  assert.strictEqual(markers[1].time, 12.5);
  assert.strictEqual(markers[2].time, 17.5);
  assert.strictEqual(markers[3].time, 22.5);
  assert.strictEqual(markers[3].name, "Waypoint 4");
});

challenge("Waypoints with empty or null list returns empty array", () => {
  assert.deepStrictEqual(computeMarkers(null), []);
  assert.deepStrictEqual(computeMarkers([]), []);
  assert.deepStrictEqual(computeMarkers(undefined), []);
});

// -----------------------------------------------------------------------------
// CHALLENGE 7: Manifest Compilation & Robustness Against Missing Metadata
// -----------------------------------------------------------------------------
console.log("\n--- CHALLENGE 7: Manifest Compilation & Edge Cases ---");

challenge("Manifest compilation handles completely empty timeline without error", () => {
  const emptyTimeline = {
    tracks: [],
    clips: [],
    transitions: [],
  };
  const manifest = compileTimelineManifestProduction("Empty", emptyTimeline);
  assert.strictEqual(manifest.project_name, "Empty");
  assert.strictEqual(manifest.total_duration_seconds, 0);
  assert.strictEqual(manifest.video_tracks.length, 0);
  assert.strictEqual(manifest.markers.length, 0);
  assert.strictEqual(manifest.aspect_ratio, "16:9");
  assert.deepStrictEqual(manifest.resolution, { width: 1920, height: 1080 });
});

challenge("Manifest compilation with orphaned clip whose track does not exist", () => {
  const timeline = {
    tracks: [
      { id: "t-valid", name: "Valid Track", type: "video", orderIndex: 0 },
    ],
    clips: [
      { id: "c-orphan", trackId: "t-nonexistent", startTime: 0, duration: 10, source: "orphan.mp4" },
    ],
    transitions: [],
  };

  // When track is undefined, track?.name.toLowerCase() in fileSystem.ts line 294:
  // Optional chaining track?.name short-circuits to undefined in JS.
  // Then undefined ? "static_popup" : "video" yields "video".
  const manifest = compileTimelineManifestProduction("OrphanTest", timeline);
  assert.strictEqual(manifest.video_tracks.length, 1);
  assert.strictEqual(manifest.video_tracks[0].type, "video");
  assert.strictEqual(manifest.video_tracks[0].clip_id, "c-orphan");
});

challenge("VULNERABILITY STRESS: Track with missing/undefined name property in manifest compilation", () => {
  // In src/services/fileSystem.ts line 294:
  // track?.name.toLowerCase().includes("popup")
  // If track exists but track.name is undefined:
  // track is defined, so track?.name is undefined.
  // Calling .toLowerCase() on undefined throws TypeError!
  const timelineWithNamelessTrack = {
    tracks: [
      { id: "t-unnamed", type: "video", orderIndex: 0 }, // name is missing/undefined
    ],
    clips: [
      { id: "c1", trackId: "t-unnamed", startTime: 0, duration: 10, source: "clip.mp4" },
    ],
    transitions: [],
  };

  try {
    compileTimelineManifestProduction("NamelessTrack", timelineWithNamelessTrack);
    assert.fail("Expected compileTimelineManifestProduction to throw TypeError on track.name.toLowerCase()");
  } catch (err) {
    assert(err instanceof TypeError, `Expected TypeError, got ${err.constructor.name}: ${err.message}`);
    noteAnomaly(
      "Unchecked track.name property access in fileSystem.ts",
      `Line 294 uses 'track?.name.toLowerCase()' instead of 'track?.name?.toLowerCase()'. Throws TypeError if track.name is undefined.`
    );
  }
});

challenge("Safe project name sanitization for output filenames", () => {
  const dirtyNames = [
    { input: "My Project / 2026 : Special & <Tags> !", expected: "My_Project___2026___Special____Tags___" },
    { input: "Trip to Kyoto ⛩️ (Summer)", expected: "Trip_to_Kyoto______Summer_" },
    { input: "Simple_Name-123", expected: "Simple_Name-123" },
  ];

  for (const { input, expected } of dirtyNames) {
    const safe = input.replace(/[^a-zA-Z0-9_-]/g, "_");
    assert.strictEqual(safe, expected);
    const filename = `${safe}_Desktop_16x9_1080p_30fps.mp4`;
    // Filename should not contain path traversal or invalid windows characters (: / \ * ? " < > |)
    assert(!/[:/\\*?"<>|]/.test(filename), `Filename contains illegal characters: ${filename}`);
  }
});

// -----------------------------------------------------------------------------
// SUMMARY
// -----------------------------------------------------------------------------
console.log("\n======================================================================");
console.log(`STRESS TEST RESULTS: ${passed} passed, ${failed} failed.`);
console.log(`ANOMALIES IDENTIFIED: ${anomalies.length}`);
for (const a of anomalies) {
  console.log(`  - ${a.name}: ${a.detail}`);
}
console.log("======================================================================");

if (failed > 0) {
  process.exit(1);
}
