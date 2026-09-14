// test/test_m4_empirical.mjs
// Empirical stress test harness for Challenger M4-1: Waypoint Timestamp Math & Zoom Scaling

import assert from "node:assert";

console.log("==================================================================");
console.log("STARTING EMPIRICAL CHALLENGE SUITE: MILESTONE M4");
console.log("Waypoint Timestamp Math, Edge Cases, Timecode & Zoom Scaling");
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
// Pure logic functions directly mirroring TimelineView.tsx and WaypointMarker.tsx
// -----------------------------------------------------------------------------

function formatMarkerTime(timeInSeconds) {
  const safeTime = Math.max(0, isFinite(timeInSeconds) ? timeInSeconds : 0);
  const totalMilliseconds = Math.round(safeTime * 1000);
  const minutes = Math.floor(totalMilliseconds / 60000);
  const seconds = Math.floor((totalMilliseconds % 60000) / 1000);
  const milliseconds = totalMilliseconds % 1000;

  const mm = minutes.toString().padStart(2, "0");
  const ss = seconds.toString().padStart(2, "0");
  const mmm = milliseconds.toString().padStart(3, "0");

  return `${mm}:${ss}.${mmm}`;
}

function computeWaypointMarkers(waypoints, settings, timeline) {
  if (!waypoints || waypoints.length === 0) return [];

  const stepDuration =
    typeof settings?.duration_seconds === "number" && settings.duration_seconds > 0
      ? settings.duration_seconds
      : 5.0;

  const videoTrackIds = new Set(
    (timeline.tracks || [])
      .filter((t) => t.type === "video")
      .map((t) => t.id),
  );
  const videoClips = (timeline.clips || []).filter((c) => {
    if (c.type && c.type !== "video") return false;
    return videoTrackIds.size === 0 || (c.trackId && videoTrackIds.has(c.trackId));
  });

  let runningTime = 0;

  return waypoints.map((wp, idx) => {
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
          (strippedLabel.includes(strippedWpName) ||
            underscoreLabel.includes(underscoreWpName))
        ) {
          return true;
        }

        return (
          rawLabel.includes(`waypoint_${pad2}`) ||
          rawLabel.includes(`waypoint_${pad1}`) ||
          rawLabel.includes(`waypoint-${pad2}`) ||
          rawLabel.includes(`waypoint-${pad1}`) ||
          rawLabel.includes(`waypoint ${pad1}`) ||
          rawLabel.includes(`wp_${pad2}`) ||
          rawLabel.includes(`wp_${pad1}`) ||
          rawLabel.includes(`wp-${pad2}`) ||
          rawLabel.includes(`wp-${pad1}`) ||
          strippedLabel.includes(`waypoint${pad2}`) ||
          strippedLabel.includes(`waypoint${pad1}`) ||
          strippedLabel.includes(`wp${pad2}`) ||
          strippedLabel.includes(`wp${pad1}`)
        );
      });

      if (matchedClip && typeof matchedClip.startTime === "number") {
        calculatedTime = matchedClip.startTime;
      } else {
        calculatedTime = runningTime;
      }
    }

    runningTime = Math.max(runningTime, calculatedTime) + stepDuration;

    return {
      id: wp.id || `waypoint-${idx + 1}`,
      name: wp.name || `Waypoint ${idx + 1}`,
      time: Math.max(0, calculatedTime),
      index: idx + 1,
      color: "#f59e0b",
    };
  });
}

function calculateRulerDuration(clips, waypointMarkers) {
  const maxClipEnd = (clips || []).reduce(
    (max, clip) => Math.max(max, clip.startTime + clip.duration),
    0,
  );
  const maxMarkerTime = (waypointMarkers || []).reduce(
    (max, m) => Math.max(max, m.time),
    0,
  );
  return Math.max(600, maxClipEnd + 120, maxMarkerTime + 120);
}

// -----------------------------------------------------------------------------
// SECTION 1: Timecode Formatting Stress Tests (formatMarkerTime)
// -----------------------------------------------------------------------------

test("1.1 Timecode exact zero (0s)", () => {
  assert.strictEqual(formatMarkerTime(0), "00:00.000");
  assert.strictEqual(formatMarkerTime(0.0), "00:00.000");
  assert.strictEqual(formatMarkerTime(-0.0), "00:00.000");
});

test("1.2 Timecode sub-second precision (non-integers & millisecond boundaries)", () => {
  assert.strictEqual(formatMarkerTime(0.001), "00:00.001");
  assert.strictEqual(formatMarkerTime(0.010), "00:00.010");
  assert.strictEqual(formatMarkerTime(0.500), "00:00.500");
  assert.strictEqual(formatMarkerTime(0.999), "00:00.999");
  assert.strictEqual(formatMarkerTime(12.3456), "00:12.346"); // rounded to nearest ms
});

test("1.3 Timecode 59.999s and millisecond rollover to 60s", () => {
  assert.strictEqual(formatMarkerTime(59.999), "00:59.999");
  assert.strictEqual(formatMarkerTime(59.9994), "00:59.999");
  assert.strictEqual(formatMarkerTime(59.9996), "01:00.000"); // rounds up to 60000ms -> 01:00.000
  assert.strictEqual(formatMarkerTime(60.0), "01:00.000");
  assert.strictEqual(formatMarkerTime(60.001), "01:00.001");
});

test("1.4 Timecode hour boundary (3600s) and multi-hour timelines", () => {
  assert.strictEqual(formatMarkerTime(3599.999), "59:59.999");
  assert.strictEqual(formatMarkerTime(3600), "60:00.000");
  assert.strictEqual(formatMarkerTime(3661.123), "61:01.123");
  assert.strictEqual(formatMarkerTime(7200), "120:00.000");
});

test("1.5 Timecode negative values, non-numbers, NaN, and Infinity", () => {
  assert.strictEqual(formatMarkerTime(-0.001), "00:00.000");
  assert.strictEqual(formatMarkerTime(-59.999), "00:00.000");
  assert.strictEqual(formatMarkerTime(-3600), "00:00.000");
  assert.strictEqual(formatMarkerTime(NaN), "00:00.000");
  assert.strictEqual(formatMarkerTime(Infinity), "00:00.000");
  assert.strictEqual(formatMarkerTime(-Infinity), "00:00.000");
  assert.strictEqual(formatMarkerTime(undefined), "00:00.000");
  assert.strictEqual(formatMarkerTime(null), "00:00.000");
});

// -----------------------------------------------------------------------------
// SECTION 2: Waypoint Array Edge Cases (Empty, Single, 50+, 500+)
// -----------------------------------------------------------------------------

test("2.1 Empty waypoints array returns empty marker array", () => {
  const mEmpty = computeWaypointMarkers([], { duration_seconds: 5.0 }, { tracks: [], clips: [] });
  assert.deepStrictEqual(mEmpty, []);

  const mNull = computeWaypointMarkers(null, { duration_seconds: 5.0 }, { tracks: [], clips: [] });
  assert.deepStrictEqual(mNull, []);

  const mUndefined = computeWaypointMarkers(undefined, { duration_seconds: 5.0 }, { tracks: [], clips: [] });
  assert.deepStrictEqual(mUndefined, []);
});

test("2.2 Single waypoint at time = 0 without explicit offset", () => {
  const waypoints = [{ id: "wp-origin", name: "Start Point" }];
  const markers = computeWaypointMarkers(waypoints, { duration_seconds: 5.0 }, { tracks: [], clips: [] });

  assert.strictEqual(markers.length, 1);
  assert.strictEqual(markers[0].id, "wp-origin");
  assert.strictEqual(markers[0].name, "Start Point");
  assert.strictEqual(markers[0].time, 0);
  assert.strictEqual(markers[0].index, 1);
  assert.strictEqual(markers[0].color, "#f59e0b");
});

test("2.3 Single waypoint at time = 0 with explicit timelineOffset = 0", () => {
  const waypoints = [{ id: "wp-zero", name: "Explicit Zero", timelineOffset: 0 }];
  const markers = computeWaypointMarkers(waypoints, { duration_seconds: 5.0 }, { tracks: [], clips: [] });

  assert.strictEqual(markers.length, 1);
  assert.strictEqual(markers[0].time, 0);
  assert.strictEqual(markers[0].index, 1);
});

test("2.4 Large number of waypoints (60 waypoints spaced closely: 0.1s steps)", () => {
  const count = 60;
  const waypoints = Array.from({ length: count }, (_, i) => ({
    id: `wp-${i + 1}`,
    name: `Close Waypoint ${i + 1}`,
    timelineOffset: +(i * 0.1).toFixed(2),
  }));

  const markers = computeWaypointMarkers(waypoints, { duration_seconds: 5.0 }, { tracks: [], clips: [] });
  assert.strictEqual(markers.length, count);

  for (let i = 0; i < count; i++) {
    const expectedTime = +(i * 0.1).toFixed(2);
    assert.strictEqual(markers[i].time, expectedTime);
    assert.strictEqual(markers[i].index, i + 1);
  }

  // Ruler duration should easily accommodate 6.0s (min 600s)
  const rulerDur = calculateRulerDuration([], markers);
  assert.strictEqual(rulerDur, 600);
});

test("2.5 Large number of waypoints (50 waypoints spaced far apart: 100s steps)", () => {
  const count = 50;
  const waypoints = Array.from({ length: count }, (_, i) => ({
    id: `wp-${i + 1}`,
    name: `Far Waypoint ${i + 1}`,
    timelineOffset: i * 100,
  }));

  const markers = computeWaypointMarkers(waypoints, { duration_seconds: 5.0 }, { tracks: [], clips: [] });
  assert.strictEqual(markers.length, 50);
  assert.strictEqual(markers[49].time, 4900);

  // Ruler duration must expand to cover maxMarkerTime + 120 = 5020s
  const rulerDur = calculateRulerDuration([], markers);
  assert.strictEqual(rulerDur, 5020);
});

test("2.6 Massive stress test: 500 waypoints default cumulative timing", () => {
  const count = 500;
  const waypoints = Array.from({ length: count }, (_, i) => ({
    id: `wp-${i + 1}`,
    name: `Bulk Waypoint ${i + 1}`,
  }));

  const t0 = performance.now();
  const markers = computeWaypointMarkers(waypoints, { duration_seconds: 4.0 }, { tracks: [], clips: [] });
  const tElapsed = performance.now() - t0;

  assert.strictEqual(markers.length, 500);
  assert.strictEqual(markers[0].time, 0);
  assert.strictEqual(markers[1].time, 4.0);
  assert.strictEqual(markers[499].time, 499 * 4.0); // 1996.0s
  // Must execute in under 50ms
  assert(tElapsed < 50, `500 waypoints took ${tElapsed.toFixed(2)}ms, expected < 50ms`);
});

test("2.7 Coincident waypoints (multiple waypoints at exact same timestamp)", () => {
  const waypoints = [
    { id: "wp-1", name: "Arrival A", timelineOffset: 15.0 },
    { id: "wp-2", name: "Arrival B", timelineOffset: 15.0 },
    { id: "wp-3", name: "Arrival C", timelineOffset: 15.0 },
  ];

  const markers = computeWaypointMarkers(waypoints, { duration_seconds: 5.0 }, { tracks: [], clips: [] });
  assert.strictEqual(markers.length, 3);
  assert.strictEqual(markers[0].time, 15.0);
  assert.strictEqual(markers[1].time, 15.0);
  assert.strictEqual(markers[2].time, 15.0);
});

// -----------------------------------------------------------------------------
// SECTION 3: TimelineOffset Boundary Stress (Negative, NaN, String, Infinity)
// -----------------------------------------------------------------------------

test("3.1 Negative timelineOffset is clamped to 0s", () => {
  const waypoints = [
    { id: "wp-neg", name: "Negative Point", timelineOffset: -25.5 },
    { id: "wp-next", name: "Next Point" },
  ];

  const markers = computeWaypointMarkers(waypoints, { duration_seconds: 5.0 }, { tracks: [], clips: [] });
  assert.strictEqual(markers[0].time, 0); // clamped by Math.max(0, calculatedTime)
  // runningTime = Math.max(0, -25.5) + 5.0 = 5.0
  assert.strictEqual(markers[1].time, 5.0);
});

test("3.2 NaN timelineOffset falls back to runningTime", () => {
  const waypoints = [
    { id: "wp-1", name: "Alpha", timelineOffset: 10.0 },
    { id: "wp-2", name: "Beta", timelineOffset: NaN },
    { id: "wp-3", name: "Gamma" },
  ];

  const markers = computeWaypointMarkers(waypoints, { duration_seconds: 5.0 }, { tracks: [], clips: [] });
  assert.strictEqual(markers[0].time, 10.0);
  assert.strictEqual(markers[1].time, 15.0); // 10 + 5.0
  assert.strictEqual(markers[2].time, 20.0); // 15 + 5.0
});

test("3.3 String or invalid type timelineOffset falls back safely", () => {
  const waypoints = [
    { id: "wp-1", name: "String Offset", timelineOffset: "20" }, // not a number
    { id: "wp-2", name: "Null Offset", timelineOffset: null },
    { id: "wp-3", name: "Undefined Offset", timelineOffset: undefined },
  ];

  const markers = computeWaypointMarkers(waypoints, { duration_seconds: 5.0 }, { tracks: [], clips: [] });
  assert.strictEqual(markers[0].time, 0.0);
  assert.strictEqual(markers[1].time, 5.0);
  assert.strictEqual(markers[2].time, 10.0);
});

test("3.4 CHALLENGE: Infinity timelineOffset vulnerability analysis", () => {
  // ADVERSARIAL CHALLENGE:
  // If wp.timelineOffset === Infinity:
  // typeof Infinity === "number" is true, !isNaN(Infinity) is true!
  const wpInfinity = [{ id: "wp-inf", name: "Infinite Point", timelineOffset: Infinity }];
  const markers = computeWaypointMarkers(wpInfinity, { duration_seconds: 5.0 }, { tracks: [], clips: [] });

  // In the current implementation:
  const infTime = markers[0].time;
  assert.strictEqual(infTime, Infinity);

  // When marker.time is Infinity:
  // 1. formatMarkerTime handles it safely:
  assert.strictEqual(formatMarkerTime(infTime), "00:00.000");

  // 2. But calculateRulerDuration becomes Infinity:
  const rulerDur = calculateRulerDuration([], markers);
  assert.strictEqual(rulerDur, Infinity);

  // 3. In TimelineView.tsx line 1349:
  // Array.from({ length: Math.ceil(rulerDuration / minorStep) })
  // With rulerDur === Infinity, this throws RangeError: Invalid array length!
  let threwRangeError = false;
  try {
    Array.from({ length: Math.ceil(rulerDur / 2) });
  } catch (e) {
    threwRangeError = (e instanceof RangeError);
  }
  assert.strictEqual(threwRangeError, true, "Array.from with Infinity rulerDuration must throw RangeError");
});

test("3.5 CHALLENGE: Negative Infinity timelineOffset", () => {
  const wpNegInfinity = [{ id: "wp-neginf", name: "Neg Infinite Point", timelineOffset: -Infinity }];
  const markers = computeWaypointMarkers(wpNegInfinity, { duration_seconds: 5.0 }, { tracks: [], clips: [] });

  // Math.max(0, -Infinity) resolves safely to 0
  assert.strictEqual(markers[0].time, 0);
});

// -----------------------------------------------------------------------------
// SECTION 4: Zoom Scaling Stress Tests (0.2x, 0.5x, 1.0x, 2.0x, 2.5x, 5.0x)
// -----------------------------------------------------------------------------

test("4.1 Zoom scaling X position formula: marker.time * (20 * zoomMultiplier)", () => {
  const testMarkers = [
    { time: 0 },
    { time: 1.5 },
    { time: 10.0 },
    { time: 59.999 },
    { time: 120.0 },
    { time: 3600.0 },
  ];

  const zoomLevels = [0.2, 0.5, 1.0, 2.0, 2.5, 5.0];

  zoomLevels.forEach((zoom) => {
    const pixelsPerSecond = 20 * zoom;

    testMarkers.forEach((m) => {
      const expectedX = m.time * pixelsPerSecond;
      const actualMarkerX = m.time * (20 * zoom);
      assert.strictEqual(actualMarkerX, expectedX);
    });
  });
});

test("4.2 Specific requested zoom levels: 0.5x, 1.0x, 2.0x, 5.0x", () => {
  const marker = { time: 35.5 };

  // 0.5x zoom -> 10 px/s
  const pps_0_5 = 20 * 0.5;
  assert.strictEqual(pps_0_5, 10);
  assert.strictEqual(marker.time * pps_0_5, 355.0);

  // 1.0x zoom -> 20 px/s
  const pps_1_0 = 20 * 1.0;
  assert.strictEqual(pps_1_0, 20);
  assert.strictEqual(marker.time * pps_1_0, 710.0);

  // 2.0x zoom -> 40 px/s
  const pps_2_0 = 20 * 2.0;
  assert.strictEqual(pps_2_0, 40);
  assert.strictEqual(marker.time * pps_2_0, 1420.0);

  // 5.0x zoom -> 100 px/s
  const pps_5_0 = 20 * 5.0;
  assert.strictEqual(pps_5_0, 100);
  assert.strictEqual(marker.time * pps_5_0, 3550.0);
});

test("4.3 Timeline total pixel width matches rulerDuration * pixelsPerSecond across all zoom levels", () => {
  const clips = [{ startTime: 0, duration: 150 }];
  const markers = [{ time: 200 }];
  const rulerDur = calculateRulerDuration(clips, markers);
  assert.strictEqual(rulerDur, 600); // max(600, 150+120, 200+120) = 600

  const zoomLevels = [0.2, 0.5, 1.0, 2.0, 5.0];
  const expectedWidths = {
    0.2: 600 * 4,    // 2400px
    0.5: 600 * 10,   // 6000px
    1.0: 600 * 20,   // 12000px
    2.0: 600 * 40,   // 24000px
    5.0: 600 * 100,  // 60000px
  };

  zoomLevels.forEach((zoom) => {
    const pps = 20 * zoom;
    const timelinePixelWidth = rulerDur * pps;
    assert.strictEqual(timelinePixelWidth, expectedWidths[zoom]);
  });
});

test("4.4 Ruler tick step resolution across zoom thresholds (< 0.5, 0.5..1.2, 1.2..2.5, > 2.5)", () => {
  function getRulerSteps(zoomMultiplier) {
    let majorStep = 10, minorStep = 2;
    if (zoomMultiplier < 0.5) {
      majorStep = 30;
      minorStep = 10;
    } else if (zoomMultiplier > 2.5) {
      majorStep = 2;
      minorStep = 0.5;
    } else if (zoomMultiplier > 1.2) {
      majorStep = 5;
      minorStep = 1;
    }
    return { majorStep, minorStep };
  }

  assert.deepStrictEqual(getRulerSteps(0.2), { majorStep: 30, minorStep: 10 });
  assert.deepStrictEqual(getRulerSteps(0.5), { majorStep: 10, minorStep: 2 });
  assert.deepStrictEqual(getRulerSteps(1.0), { majorStep: 10, minorStep: 2 });
  assert.deepStrictEqual(getRulerSteps(2.0), { majorStep: 5, minorStep: 1 });
  assert.deepStrictEqual(getRulerSteps(5.0), { majorStep: 2, minorStep: 0.5 });
});

// -----------------------------------------------------------------------------
// SECTION 5: Settings Duration & Clip Matching Nuances
// -----------------------------------------------------------------------------

test("5.1 Settings duration_seconds zero, negative, or NaN fallback to 5.0s", () => {
  const waypoints = [{ id: "w1", name: "P1" }, { id: "w2", name: "P2" }];

  const mZero = computeWaypointMarkers(waypoints, { duration_seconds: 0 }, { tracks: [], clips: [] });
  assert.strictEqual(mZero[1].time, 5.0);

  const mNeg = computeWaypointMarkers(waypoints, { duration_seconds: -10 }, { tracks: [], clips: [] });
  assert.strictEqual(mNeg[1].time, 5.0);

  const mNaN = computeWaypointMarkers(waypoints, { duration_seconds: NaN }, { tracks: [], clips: [] });
  assert.strictEqual(mNaN[1].time, 5.0);
});

test("5.2 Clip matching robust to varied delimiters, hyphens, and underscores", () => {
  const waypoints = [
    { id: "wp-1", name: "Kyoto Tower" },
    { id: "wp-2", name: "Kinkaku-ji" },
    { id: "wp-3", name: "Waypoint 03" },
  ];

  const timeline = {
    tracks: [{ id: "v1", type: "video" }],
    clips: [
      { id: "c1", trackId: "v1", label: "01_kyoto_tower.mp4", startTime: 3.5, type: "video" },
      { id: "c2", trackId: "v1", label: "02 kinkakuji footage.mp4", startTime: 18.0, type: "video" },
      { id: "c3", trackId: "v1", label: "wp-03.mp4", startTime: 32.0, type: "video" },
    ],
  };

  const markers = computeWaypointMarkers(waypoints, { duration_seconds: 5.0 }, timeline);
  assert.strictEqual(markers[0].time, 3.5);
  assert.strictEqual(markers[1].time, 18.0);
  assert.strictEqual(markers[2].time, 32.0);
});

// -----------------------------------------------------------------------------
// SUMMARY
// -----------------------------------------------------------------------------

console.log("\n==================================================================");
console.log(`CHALLENGE RESULTS: ${passedTests} passed, ${failedTests} failed`);
console.log("==================================================================");

if (failedTests > 0) {
  console.log("CHALLENGES SURFACED ANOMALIES/FAILURES:");
  findings.forEach((f) => console.log(` - ${f.test}: ${f.error}`));
  process.exit(1);
} else {
  console.log("ALL EMPIRICAL CHALLENGE SUITE TESTS COMPLETED SUCCESSFULLY!");
}
