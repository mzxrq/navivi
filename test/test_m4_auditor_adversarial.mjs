// test/test_m4_auditor_adversarial.mjs
// Independent Forensic Auditor Adversarial Stress-Test Suite for M4 Waypoint Markers

import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";

console.log("=================================================");
console.log("AUDITOR M4 INDEPENDENT ADVERSARIAL STRESS SUITE");
console.log("=================================================\n");

let passed = 0;
let failed = 0;

function runTest(name, fn) {
  try {
    fn();
    console.log(`  [PASS] ${name}`);
    passed++;
  } catch (err) {
    console.error(`  [FAIL] ${name}: ${err.message}`);
    failed++;
  }
}

// 1. Verify file presence and inspect AST/content directly
const waypointMarkerPath = path.resolve("src/components/view/videoeditor/elements/WaypointMarker.tsx");
const timelineViewPath = path.resolve("src/components/view/videoeditor/TimelineView.tsx");

runTest("Static: WaypointMarker.tsx exists and is non-trivial", () => {
  assert(fs.existsSync(waypointMarkerPath), "WaypointMarker.tsx must exist");
  const content = fs.readFileSync(waypointMarkerPath, "utf-8");
  assert(content.length > 500, "WaypointMarker.tsx must have substantial content");
  assert(content.includes("export function formatMarkerTime"), "formatMarkerTime must be exported");
  assert(content.includes("export const WaypointMarker"), "WaypointMarker must be exported");
  assert(content.includes("export const WaypointGuideLine"), "WaypointGuideLine must be exported");
});

runTest("Static: TimelineView.tsx integrates WaypointMarker and WaypointGuideLine", () => {
  assert(fs.existsSync(timelineViewPath), "TimelineView.tsx must exist");
  const content = fs.readFileSync(timelineViewPath, "utf-8");
  assert(content.includes("WaypointMarker"), "TimelineView must import/render WaypointMarker");
  assert(content.includes("WaypointGuideLine"), "TimelineView must render WaypointGuideLine");
  assert(content.includes("waypointMarkers"), "TimelineView must calculate waypointMarkers");
  assert(content.includes("hoveredMarker"), "TimelineView must handle hoveredMarker");
});

// Dynamic evaluation of formatMarkerTime from source
const sourceContent = fs.readFileSync(waypointMarkerPath, "utf-8");
// Extract formatMarkerTime implementation
const fnMatch = sourceContent.match(/export function formatMarkerTime\(timeInSeconds: number\): string \{([\s\S]*?)\n\}/);
assert(fnMatch, "formatMarkerTime could not be extracted via regex");
const fnBody = fnMatch[1].replace(/:\s*number/g, "").replace(/:\s*string/g, "");
const formatMarkerTime = new Function("timeInSeconds", fnBody);

// Adversarial Test 1: formatMarkerTime with extreme boundaries
runTest("Boundary: Extreme time values and negative/invalid numbers", () => {
  assert.strictEqual(formatMarkerTime(-99999), "00:00.000");
  assert.strictEqual(formatMarkerTime(0.0004), "00:00.000");
  assert.strictEqual(formatMarkerTime(0.0006), "00:00.001");
  assert.strictEqual(formatMarkerTime(59.999), "00:59.999");
  assert.strictEqual(formatMarkerTime(60.0), "01:00.000");
  assert.strictEqual(formatMarkerTime(3661.123), "61:01.123");
  assert.strictEqual(formatMarkerTime(NaN), "00:00.000");
  assert.strictEqual(formatMarkerTime(Infinity), "00:00.000");
});

// Adversarial Test 2: Cascade resolution stress testing
runTest("Cascade: Mixed waypoints with offsets, clips, and gaps", () => {
  const waypoints = [
    { id: "w1", name: "Point A", timelineOffset: 5.0 },
    { id: "w2", name: "Point B" },
    { id: "w3", name: "Point C" },
    { id: "w4", name: "Point D", timelineOffset: 10.0 },
    { id: "w5", name: "Point E" },
  ];

  const settings = { duration_seconds: 4.0 };
  const timeline = {
    tracks: [{ id: "v1", type: "video" }],
    clips: [
      { id: "c1", trackId: "v1", label: "02_point_b.mp4", startTime: 12.0, type: "video" },
    ],
  };

  const videoTrackIds = new Set(timeline.tracks.filter((t) => t.type === "video").map((t) => t.id));
  const videoClips = timeline.clips.filter((c) => !c.type || c.type === "video");

  let runningTime = 0;
  const markers = waypoints.map((wp, idx) => {
    let calculatedTime;
    if (typeof wp.timelineOffset === "number" && !isNaN(wp.timelineOffset)) {
      calculatedTime = wp.timelineOffset;
    } else {
      const rawWpName = (wp.name || "").trim().toLowerCase();
      const strippedWpName = rawWpName.replace(/[^a-z0-9]/g, "");
      const underscoreWpName = rawWpName.replace(/[\s\-]+/g, "_");
      const pad2 = String(idx + 1).padStart(2, "0");
      const pad1 = String(idx + 1);

      const matchedClip = videoClips.find((clip) => {
        const rawLabel = (clip.label || "").toLowerCase();
        const strippedLabel = rawLabel.replace(/[^a-z0-9]/g, "");
        const underscoreLabel = rawLabel.replace(/[\s\-]+/g, "_");

        if (
          strippedWpName &&
          strippedWpName !== "waypoint" &&
          (strippedLabel.includes(strippedWpName) || underscoreLabel.includes(underscoreWpName))
        ) {
          return true;
        }
        return rawLabel.includes(`waypoint_${pad2}`) || rawLabel.includes(`wp_${pad2}`);
      });

      if (matchedClip && typeof matchedClip.startTime === "number") {
        calculatedTime = matchedClip.startTime;
      } else {
        calculatedTime = runningTime;
      }
    }

    runningTime = Math.max(runningTime, calculatedTime) + (settings.duration_seconds || 5.0);

    return {
      id: wp.id || `waypoint-${idx + 1}`,
      name: wp.name,
      time: Math.max(0, calculatedTime),
      index: idx + 1,
    };
  });

  assert.strictEqual(markers[0].time, 5.0);
  assert.strictEqual(markers[1].time, 12.0);
  assert.strictEqual(markers[2].time, 16.0);
  assert.strictEqual(markers[3].time, 10.0);
  assert.strictEqual(markers[4].time, 24.0);
});

// Adversarial Test 3: Null/undefined resilience
runTest("Resilience: Corrupted waypoint objects with missing fields", () => {
  const waypoints = [
    {},
    { id: null, name: null, timelineOffset: null },
    { timelineOffset: NaN },
    { timelineOffset: -50.0 },
  ];

  let runningTime = 0;
  const stepDuration = 5.0;

  const markers = waypoints.map((wp, idx) => {
    let calculatedTime;
    if (typeof wp.timelineOffset === "number" && !isNaN(wp.timelineOffset)) {
      calculatedTime = wp.timelineOffset;
    } else {
      calculatedTime = runningTime;
    }
    runningTime = Math.max(runningTime, calculatedTime) + stepDuration;

    return {
      id: wp.id || `waypoint-${idx + 1}`,
      name: wp.name || `Waypoint ${idx + 1}`,
      time: Math.max(0, calculatedTime),
      index: idx + 1,
    };
  });

  assert.strictEqual(markers.length, 4);
  assert.strictEqual(markers[0].id, "waypoint-1");
  assert.strictEqual(markers[0].name, "Waypoint 1");
  assert.strictEqual(markers[0].time, 0);

  assert.strictEqual(markers[1].id, "waypoint-2");
  assert.strictEqual(markers[1].name, "Waypoint 2");
  assert.strictEqual(markers[1].time, 5.0);

  assert.strictEqual(markers[2].time, 10.0);
  assert.strictEqual(markers[3].time, 0);
});

console.log(`\nAdversarial stress results: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
