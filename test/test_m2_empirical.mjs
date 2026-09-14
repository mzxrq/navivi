// test/test_m2_empirical.mjs
// Empirical test harness for Challenger M2-2: Color Filters & UI Robustness

import assert from "node:assert";

console.log("=================================================");
console.log("STARTING EMPIRICAL CHALLENGE SUITE: MILESTONE M2");
console.log("=================================================\n");

let passedTests = 0;
let failedTests = 0;

function test(name, fn) {
  try {
    fn();
    console.log(`  [PASS] ${name}`);
    passedTests++;
  } catch (err) {
    console.error(`  [FAIL] ${name}`);
    console.error(`         ${err.message}`);
    failedTests++;
  }
}

// -----------------------------------------------------------------------------
// SUITE 1: TransformableClip.tsx sceneFunc Canvas Filter Stress Testing
// -----------------------------------------------------------------------------
console.log("--- SUITE 1: TransformableClip sceneFunc & Canvas Filter ---");

// Model the exact sceneFunc implementation from TransformableClip.tsx
function runSceneFunc({ clip, activeMedia, videoSize, shape, ctxMock }) {
  if (!activeMedia) return;
  const ctx = ctxMock;
  const b = clip.effects?.brightness ?? 0;
  const c = clip.effects?.contrast ?? 0;
  const s = clip.effects?.saturation ?? 0;
  const hasColorFilter = b !== 0 || c !== 0 || s !== 0;

  const prevFilter = ctx.filter;
  if (hasColorFilter) {
    const bVal = Math.max(0, 1 + b / 100);
    const cVal = Math.max(0, 1 + c / 100);
    const sVal = Math.max(0, 1 + s / 100);
    ctx.filter = `brightness(${bVal}) contrast(${cVal}) saturate(${sVal})`;
  }

  const w = shape.width() || videoSize.width;
  const h = shape.height() || videoSize.height;
  ctx.drawImage(activeMedia, 0, 0, w, h);

  if (hasColorFilter) {
    ctx.filter = prevFilter || "none";
  }
}

function createMockCtx(initialFilter = "none") {
  return {
    filter: initialFilter,
    drawn: [],
    drawImage(media, x, y, w, h) {
      this.drawn.push({
        media,
        x,
        y,
        w,
        h,
        filterAtDraw: this.filter,
      });
    },
  };
}

test("TC 1.1: Missing effects object (undefined) draws without modifying filter", () => {
  const ctx = createMockCtx("none");
  runSceneFunc({
    clip: { id: "clip-1" }, // no effects
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 1);
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "none");
  assert.strictEqual(ctx.filter, "none");
});

test("TC 1.2: Empty effects object ({}) draws without modifying filter", () => {
  const ctx = createMockCtx("none");
  runSceneFunc({
    clip: { id: "clip-1", effects: {} },
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 1);
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "none");
  assert.strictEqual(ctx.filter, "none");
});

test("TC 1.3: Zero effects (b=0, c=0, s=0) bypasses filter overhead", () => {
  const ctx = createMockCtx("none");
  runSceneFunc({
    clip: { id: "clip-1", effects: { brightness: 0, contrast: 0, saturation: 0 } },
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 1);
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "none");
  assert.strictEqual(ctx.filter, "none");
});

test("TC 1.4: Slider maximums (+100, +100, +100) produces valid CSS filter and restores", () => {
  const ctx = createMockCtx("none");
  runSceneFunc({
    clip: { id: "clip-1", effects: { brightness: 100, contrast: 100, saturation: 100 } },
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 1);
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "brightness(2) contrast(2) saturate(2)");
  assert.strictEqual(ctx.filter, "none", "Filter must be restored to initial state");
});

test("TC 1.5: Slider minimums (-100, -100, -100) produces non-negative clamp (0) and restores", () => {
  const ctx = createMockCtx("none");
  runSceneFunc({
    clip: { id: "clip-1", effects: { brightness: -100, contrast: -100, saturation: -100 } },
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 1);
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "brightness(0) contrast(0) saturate(0)");
  assert.strictEqual(ctx.filter, "none");
});

test("TC 1.6: Extreme out-of-bounds negative values (-250) clamp to 0 (no invalid CSS)", () => {
  const ctx = createMockCtx("none");
  runSceneFunc({
    clip: { id: "clip-1", effects: { brightness: -250, contrast: -500, saturation: -1000 } },
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 1);
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "brightness(0) contrast(0) saturate(0)");
  assert.strictEqual(ctx.filter, "none");
});

test("TC 1.7: Extreme positive values (+500) compute mathematically sound filter ratios", () => {
  const ctx = createMockCtx("none");
  runSceneFunc({
    clip: { id: "clip-1", effects: { brightness: 500, contrast: 250, saturation: 150 } },
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 1);
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "brightness(6) contrast(3.5) saturate(2.5)");
  assert.strictEqual(ctx.filter, "none");
});

test("TC 1.8: Partial effects ({ contrast: 40 }) leaves other params at default (1)", () => {
  const ctx = createMockCtx("none");
  runSceneFunc({
    clip: { id: "clip-1", effects: { contrast: 40 } },
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 1);
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "brightness(1) contrast(1.4) saturate(1)");
  assert.strictEqual(ctx.filter, "none");
});

test("TC 1.9: Context state restoration with custom pre-existing filter", () => {
  const ctx = createMockCtx("blur(4px)");
  runSceneFunc({
    clip: { id: "clip-1", effects: { brightness: 20 } },
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 1);
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "brightness(1.2) contrast(1) saturate(1)");
  assert.strictEqual(ctx.filter, "blur(4px)", "Pre-existing filter must be preserved exactly");
});

test("TC 1.10: Context state restoration with empty string pre-existing filter", () => {
  const ctx = createMockCtx("");
  runSceneFunc({
    clip: { id: "clip-1", effects: { brightness: 20 } },
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.filter, "none", "Empty string filter safely restored as 'none'");
});

test("TC 1.11: Multi-clip consecutive render does NOT pollute sibling clips", () => {
  const ctx = createMockCtx("none");
  // Clip A has heavy filter
  runSceneFunc({
    clip: { id: "clip-A", effects: { brightness: 80, contrast: -50, saturation: 100 } },
    activeMedia: "media-A",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });
  // Clip B has NO filter
  runSceneFunc({
    clip: { id: "clip-B" },
    activeMedia: "media-B",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 2);
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "brightness(1.8) contrast(0.5) saturate(2)");
  assert.strictEqual(ctx.drawn[1].filterAtDraw, "none", "Clip B must not inherit Clip A's filter");
  assert.strictEqual(ctx.filter, "none");
});

test("TC 1.12: Active media null/undefined safely early-returns without exception", () => {
  const ctx = createMockCtx("none");
  runSceneFunc({
    clip: { id: "clip-1", effects: { brightness: 50 } },
    activeMedia: null,
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  assert.strictEqual(ctx.drawn.length, 0);
  assert.strictEqual(ctx.filter, "none");
});

test("TC 1.13: NaN input behavior analysis", () => {
  const ctx = createMockCtx("none");
  runSceneFunc({
    clip: { id: "clip-1", effects: { brightness: NaN } },
    activeMedia: "mock-image",
    videoSize: { width: 1920, height: 1080 },
    shape: { width: () => 1920, height: () => 1080 },
    ctxMock: ctx,
  });

  // NaN ?? 0 evaluates to NaN in JavaScript, so brightness(NaN) is constructed
  assert.strictEqual(ctx.drawn[0].filterAtDraw, "brightness(NaN) contrast(1) saturate(1)");
  // ctx.filter is still safely restored to 'none'
  assert.strictEqual(ctx.filter, "none");
});

// -----------------------------------------------------------------------------
// SUITE 2: TransitionsPanel Library & Filtering Stress Testing
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 2: TransitionsPanel Library, Search & Categories ---");

const TRANSITION_LIBRARY = [
  {
    shader: "glsl-crossfade",
    name: "Crossfade",
    category: "Dissolve",
    description: "Smooth linear dissolve blending outgoing and incoming clips",
    colorFrom: "#3B82F6",
    colorTo: "#EC4899",
  },
  {
    shader: "glsl-wipe",
    name: "Wipe",
    category: "Wipe & Slide",
    description: "Linear directional wipe from left to right",
    colorFrom: "#10B981",
    colorTo: "#6366F1",
  },
  {
    shader: "glsl-slide",
    name: "Slide",
    category: "Wipe & Slide",
    description: "Push transition smoothly sliding incoming clip from left",
    colorFrom: "#F59E0B",
    colorTo: "#8B5CF6",
  },
  {
    shader: "glsl-dissolve",
    name: "Dissolve",
    category: "Dissolve",
    description: "Dithering noise pixel dissolve between scenes",
    colorFrom: "#06B6D4",
    colorTo: "#F43F5E",
  },
  {
    shader: "glsl-dreamy",
    name: "Dreamy",
    category: "Warp & Distortion",
    description: "Ethereal sinusoidal wave distortion and color blend",
    colorFrom: "#8B5CF6",
    colorTo: "#F59E0B",
  },
  {
    shader: "glsl-directionalwarp",
    name: "Directional Warp",
    category: "Warp & Distortion",
    description: "Angular diagonal stretch and perspective displacement",
    colorFrom: "#EC4899",
    colorTo: "#3B82F6",
  },
  {
    shader: "glsl-pixelize",
    name: "Pixelize",
    category: "Stylized",
    description: "Progressive mosaic pixel grid reveal",
    colorFrom: "#14B8A6",
    colorTo: "#F97316",
  },
  {
    shader: "glsl-multiply_blend",
    name: "Multiply Blend",
    category: "Stylized",
    description: "Luminance photographic multiply overlay",
    colorFrom: "#6366F1",
    colorTo: "#E11D48",
  },
  {
    shader: "glsl-crosswarp",
    name: "Cross Warp",
    category: "Warp & Distortion",
    description: "Double-sided horizontal perspective warp effect",
    colorFrom: "#3B82F6",
    colorTo: "#10B981",
  },
  {
    shader: "glsl-burn",
    name: "Burn",
    category: "Stylized",
    description: "High-exposure film burn and fiery glow reveal",
    colorFrom: "#EF4444",
    colorTo: "#F59E0B",
  },
];

const CATEGORIES = ["All", "Dissolve", "Wipe & Slide", "Warp & Distortion", "Stylized"];

function filterTransitions(library, category, query) {
  return library.filter((item) => {
    const matchesCategory = category === "All" || item.category === category;
    const matchesSearch =
      item.name.toLowerCase().includes(query.toLowerCase()) ||
      item.description.toLowerCase().includes(query.toLowerCase());
    return matchesCategory && matchesSearch;
  });
}

test("TC 2.1: Default view (All, empty query) returns all 10 presets", () => {
  const result = filterTransitions(TRANSITION_LIBRARY, "All", "");
  assert.strictEqual(result.length, 10);
});

test("TC 2.2: Category filtering returns exact expected items per category", () => {
  const dissolves = filterTransitions(TRANSITION_LIBRARY, "Dissolve", "");
  assert.strictEqual(dissolves.length, 2);
  assert.deepStrictEqual(dissolves.map(d => d.shader), ["glsl-crossfade", "glsl-dissolve"]);

  const wipes = filterTransitions(TRANSITION_LIBRARY, "Wipe & Slide", "");
  assert.strictEqual(wipes.length, 2);
  assert.deepStrictEqual(wipes.map(d => d.shader), ["glsl-wipe", "glsl-slide"]);

  const warps = filterTransitions(TRANSITION_LIBRARY, "Warp & Distortion", "");
  assert.strictEqual(warps.length, 3);
  assert.deepStrictEqual(warps.map(d => d.shader), ["glsl-dreamy", "glsl-directionalwarp", "glsl-crosswarp"]);

  const stylized = filterTransitions(TRANSITION_LIBRARY, "Stylized", "");
  assert.strictEqual(stylized.length, 3);
  assert.deepStrictEqual(stylized.map(d => d.shader), ["glsl-pixelize", "glsl-multiply_blend", "glsl-burn"]);
});

test("TC 2.3: Non-existent category returns empty array without error", () => {
  const result = filterTransitions(TRANSITION_LIBRARY, "3D", "");
  assert.strictEqual(result.length, 0);
});

test("TC 2.4: Empty search filter results returns empty array without error", () => {
  const result = filterTransitions(TRANSITION_LIBRARY, "All", "xyz_non_existent_search");
  assert.strictEqual(result.length, 0);
});

test("TC 2.5: Search matches case-insensitively on name and description", () => {
  const byName = filterTransitions(TRANSITION_LIBRARY, "All", "cRoSsFaDe");
  assert.strictEqual(byName.length, 1);
  assert.strictEqual(byName[0].shader, "glsl-crossfade");

  const byDesc = filterTransitions(TRANSITION_LIBRARY, "All", "sinusoidal");
  assert.strictEqual(byDesc.length, 1);
  assert.strictEqual(byDesc[0].shader, "glsl-dreamy");
});

test("TC 2.6: Drag payload packaging contains all required fields", () => {
  const selectedDuration = 1.5;
  const item = TRANSITION_LIBRARY[0];
  const payloadStr = JSON.stringify({
    type: "transition",
    shader: item.shader,
    name: item.name,
    duration: selectedDuration,
  });

  const parsed = JSON.parse(payloadStr);
  assert.strictEqual(parsed.type, "transition");
  assert.strictEqual(parsed.shader, "glsl-crossfade");
  assert.strictEqual(parsed.name, "Crossfade");
  assert.strictEqual(parsed.duration, 1.5);
});

test("TC 2.7: Duration bounds selector options validation", () => {
  const allowedDurations = [0.5, 1.0, 1.5, 2.0];
  for (const dur of allowedDurations) {
    assert.strictEqual(typeof dur, "number");
    assert.ok(dur > 0, "Duration must be positive");
    assert.ok(Number.isFinite(dur), "Duration must be finite");
  }
});

// -----------------------------------------------------------------------------
// SUITE 3: TransitionsPanel Action & TimelineTrack Cut Matching Stress Testing
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 3: Transition Apply & TimelineTrack Cut Matching ---");

function simulateApplyToSelected({ selectedClipIds, timeline, item, selectedDuration }) {
  let toastEmitted = null;
  const showToast = (msg, type) => {
    toastEmitted = { msg, type };
  };

  if (!selectedClipIds || selectedClipIds.length === 0) {
    showToast("Select a clip on the timeline or drag this transition onto a cut!", "info");
    return { timeline, toastEmitted, applied: false };
  }

  const updatedClips = timeline.clips.map((clip) => {
    if (selectedClipIds.includes(clip.id)) {
      return {
        ...clip,
        transitionIn: item.shader,
        fadeIn: selectedDuration,
      };
    }
    return clip;
  });

  showToast(`Applied ${item.name} transition to selected clip`, "success");
  return {
    timeline: { ...timeline, clips: updatedClips },
    toastEmitted,
    applied: true,
  };
}

test("TC 3.1: Apply to selected when no clip is selected warns gracefully", () => {
  const initialTimeline = {
    clips: [
      { id: "c1", startTime: 0, duration: 5 },
      { id: "c2", startTime: 5, duration: 5 },
    ],
  };

  const res = simulateApplyToSelected({
    selectedClipIds: [],
    timeline: initialTimeline,
    item: TRANSITION_LIBRARY[0],
    selectedDuration: 1.0,
  });

  assert.strictEqual(res.applied, false);
  assert.strictEqual(res.toastEmitted.type, "info");
  assert.deepStrictEqual(res.timeline, initialTimeline);
});

test("TC 3.2: Apply to selected with 1 clip updates only target clip", () => {
  const initialTimeline = {
    clips: [
      { id: "c1", startTime: 0, duration: 5 },
      { id: "c2", startTime: 5, duration: 5 },
    ],
  };

  const res = simulateApplyToSelected({
    selectedClipIds: ["c2"],
    timeline: initialTimeline,
    item: TRANSITION_LIBRARY[0],
    selectedDuration: 1.5,
  });

  assert.strictEqual(res.applied, true);
  assert.strictEqual(res.toastEmitted.type, "success");
  assert.strictEqual(res.timeline.clips[1].transitionIn, "glsl-crossfade");
  assert.strictEqual(res.timeline.clips[1].fadeIn, 1.5);
  assert.strictEqual(res.timeline.clips[0].transitionIn, undefined);
});

// Model TimelineTrack cut detection logic
function simulateCutDrop({ trackClips, dropTime, asset }) {
  let toastEmitted = null;
  const showToast = (msg, type) => {
    toastEmitted = { msg, type };
  };

  const sortedClips = [...trackClips].sort((a, b) => a.startTime - b.startTime);
  let bestCut = null;
  let minDiff = Infinity;

  for (let i = 0; i < sortedClips.length - 1; i++) {
    const leftClip = sortedClips[i];
    const rightClip = sortedClips[i + 1];
    const cutTime = leftClip.startTime + leftClip.duration;

    if (Math.abs(cutTime - rightClip.startTime) < 0.1) {
      const diff = Math.abs(cutTime - dropTime);
      if (diff < minDiff && diff < 1.5) {
        minDiff = diff;
        bestCut = { left: leftClip, right: rightClip, cutTime };
      }
    }
  }

  if (!bestCut) {
    showToast("Drop transitions directly on the cut between two clips!", "warning");
    return { success: false, toastEmitted };
  }

  const transDuration = asset.duration || 1.0;
  return {
    success: true,
    bestCut,
    transDuration,
    transitionIn: asset.shader,
    fadeIn: transDuration,
    transitionOut: asset.shader,
    fadeOut: transDuration,
    transitionStartTime: bestCut.cutTime - transDuration / 2,
  };
}

test("TC 3.3: TimelineTrack cut detection succeeds when dropped near adjacent clips cut (< 1.5s)", () => {
  const trackClips = [
    { id: "clipA", startTime: 0, duration: 10 },
    { id: "clipB", startTime: 10, duration: 10 },
  ];
  // Cut is at 10.0, drop is at 10.2 (diff 0.2s < 1.5s)
  const res = simulateCutDrop({
    trackClips,
    dropTime: 10.2,
    asset: { type: "transition", shader: "glsl-wipe", duration: 1.0 },
  });

  assert.strictEqual(res.success, true);
  assert.strictEqual(res.bestCut.left.id, "clipA");
  assert.strictEqual(res.bestCut.right.id, "clipB");
  assert.strictEqual(res.transitionStartTime, 9.5); // centered at 10.0 with 1.0s duration
  assert.strictEqual(res.transitionIn, "glsl-wipe");
});

test("TC 3.4: TimelineTrack cut detection rejects drop too far from cut (> 1.5s)", () => {
  const trackClips = [
    { id: "clipA", startTime: 0, duration: 10 },
    { id: "clipB", startTime: 10, duration: 10 },
  ];
  // Cut is at 10.0, drop is at 12.0 (diff 2.0s > 1.5s)
  const res = simulateCutDrop({
    trackClips,
    dropTime: 12.0,
    asset: { type: "transition", shader: "glsl-wipe", duration: 1.0 },
  });

  assert.strictEqual(res.success, false);
  assert.strictEqual(res.toastEmitted.type, "warning");
});

test("TC 3.5: TimelineTrack cut detection rejects clips with gap (> 0.1s)", () => {
  const trackClips = [
    { id: "clipA", startTime: 0, duration: 10 },
    { id: "clipB", startTime: 10.5, duration: 10 }, // 0.5s gap
  ];
  // Drop is at 10.2
  const res = simulateCutDrop({
    trackClips,
    dropTime: 10.2,
    asset: { type: "transition", shader: "glsl-wipe", duration: 1.0 },
  });

  assert.strictEqual(res.success, false);
  assert.strictEqual(res.toastEmitted.type, "warning");
});

test("TC 3.6: TimelineTrack cut detection handles 0 clips and 1 clip tracks safely", () => {
  const res0 = simulateCutDrop({
    trackClips: [],
    dropTime: 5.0,
    asset: { type: "transition", shader: "glsl-wipe", duration: 1.0 },
  });
  assert.strictEqual(res0.success, false);

  const res1 = simulateCutDrop({
    trackClips: [{ id: "c1", startTime: 0, duration: 5 }],
    dropTime: 5.0,
    asset: { type: "transition", shader: "glsl-wipe", duration: 1.0 },
  });
  assert.strictEqual(res1.success, false);
});

// -----------------------------------------------------------------------------
// SUMMARY
// -----------------------------------------------------------------------------
console.log("\n=================================================");
console.log(`TEST SUITE RESULTS: ${passedTests} PASSED, ${failedTests} FAILED`);
console.log("=================================================");

if (failedTests > 0) {
  process.exit(1);
} else {
  process.exit(0);
}
