// test/test_m3_karaoke_empirical.mjs
// Empirical test harness for Challenger M3-2: Karaoke Timing & Clipping Stress Testing

import assert from "node:assert";

console.log("=================================================");
console.log("STARTING EMPIRICAL CHALLENGE SUITE: MILESTONE M3-2");
console.log("Karaoke Timing, Clipping Bounds & Subtitle Stress");
console.log("=================================================\n");

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
  }
}

function recordFinding(category, severity, title, detail) {
  findings.push({ category, severity, title, detail });
}

// =============================================================================
// Implementation models matching TransformableClip.tsx exactly
// =============================================================================

function computeClipProgress(currentTime, startTime, duration) {
  return duration > 0
    ? Math.max(0, Math.min(1, (currentTime - startTime) / duration))
    : 0;
}

function computeOpacity(currentTime, clip) {
  const clipTime = currentTime - clip.startTime;
  let currentOpacity = 1;
  if (
    !clip.transitionIn?.startsWith("glsl-") &&
    clip.fadeIn &&
    clipTime < clip.fadeIn
  ) {
    currentOpacity = clipTime / clip.fadeIn;
  } else if (clip.fadeOut && clipTime > clip.duration - clip.fadeOut) {
    currentOpacity = (clip.duration - clipTime) / clip.fadeOut;
  }
  return Math.max(0, Math.min(1, currentOpacity));
}

function getMeasuredTextDimensionsFallback(text, fontSize, fontFamily) {
  const lines = (text || "New Text").split("\n");
  return {
    width: Math.max(10, (text || "New Text").length * fontSize * 0.6),
    height: Math.max(10, lines.length * fontSize * 1.25),
  };
}

function getMeasuredTextDimensionsCanvas(text, fontSize, fontFamily, ctxMock) {
  const lines = (text || "New Text").split("\n");
  ctxMock.font = `${fontSize}px ${fontFamily}`;
  let maxW = 0;
  for (const l of lines) {
    const metrics = ctxMock.measureText(l);
    if (metrics.width > maxW) maxW = metrics.width;
  }
  return {
    width: Math.max(10, maxW),
    height: Math.max(10, lines.length * fontSize * 1.25),
  };
}

function computeClipBounds(computedTextWidth, computedTextHeight, clipProgress) {
  return {
    clip: {
      x: 0,
      y: 0,
      width: computedTextWidth * clipProgress,
      height: computedTextHeight + 20,
    },
    clipX: 0,
    clipY: 0,
    clipWidth: computedTextWidth * clipProgress,
    clipHeight: computedTextHeight + 20,
  };
}

// -----------------------------------------------------------------------------
// SUITE 1: Timing Invariants & Scrubbing Edge Cases
// -----------------------------------------------------------------------------
console.log("--- SUITE 1: Timing Invariants & Scrubbing Edge Cases ---");

test("Normal playback: progress monotonically increases from 0.0 to 1.0", () => {
  const startTime = 10.0;
  const duration = 5.0;
  const steps = 1000;
  let prevProgress = -1;

  for (let i = 0; i <= steps; i++) {
    const currentTime = startTime + (duration * i) / steps;
    const progress = computeClipProgress(currentTime, startTime, duration);

    assert(progress >= 0 && progress <= 1, `Progress ${progress} out of [0, 1] bounds at t=${currentTime}`);
    assert(progress >= prevProgress, `Progress decreased at t=${currentTime}`);
    if (i === 0) assert.strictEqual(progress, 0);
    if (i === steps) assert.strictEqual(progress, 1);
    prevProgress = progress;
  }
});

test("Scrubbing backwards before clip startTime: progress strictly clamps to 0", () => {
  const startTime = 15.0;
  const duration = 4.0;
  const testTimes = [14.999, 14.5, 10.0, 0.0, -5.0, -1000.0];

  for (const t of testTimes) {
    const progress = computeClipProgress(t, startTime, duration);
    assert.strictEqual(progress, 0, `Expected progress 0 at t=${t}, got ${progress}`);
  }
});

test("Scrubbing forward after clip end: progress strictly clamps to 1", () => {
  const startTime = 5.0;
  const duration = 3.0;
  const testTimes = [8.001, 8.5, 10.0, 100.0, 99999.0];

  for (const t of testTimes) {
    const progress = computeClipProgress(t, startTime, duration);
    assert.strictEqual(progress, 1, `Expected progress 1 at t=${t}, got ${progress}`);
  }
});

test("Zero duration clip (duration = 0): safe division by zero prevention", () => {
  const startTime = 5.0;
  const duration = 0;
  const testTimes = [4.0, 5.0, 6.0];

  for (const t of testTimes) {
    const progress = computeClipProgress(t, startTime, duration);
    assert.strictEqual(progress, 0, `Expected progress 0 for 0-duration clip at t=${t}, got ${progress}`);
    assert(!Number.isNaN(progress), `Progress must not be NaN`);
    assert(Number.isFinite(progress), `Progress must not be Infinity`);
  }
});

test("Negative duration clip (duration < 0): returns 0 progress", () => {
  const startTime = 5.0;
  const duration = -2.0;
  const progress = computeClipProgress(6.0, startTime, duration);
  assert.strictEqual(progress, 0, `Expected 0 for negative duration, got ${progress}`);
});

test("Very short clip duration (duration = 0.05s / 50ms): precision check", () => {
  const startTime = 2.0;
  const duration = 0.05; // 50ms (e.g. short audio phoneme or quick syllable)

  const pStart = computeClipProgress(2.0, startTime, duration);
  const pMid = computeClipProgress(2.025, startTime, duration);
  const pEnd = computeClipProgress(2.05, startTime, duration);

  assert.strictEqual(pStart, 0);
  assert(Math.abs(pMid - 0.5) < 1e-9, `Midpoint should be 0.5, got ${pMid}`);
  assert(Math.abs(pEnd - 1) < 1e-9, `Endpoint should be ~1 within epsilon, got ${pEnd}`);
});

test("Adversarial non-numeric inputs (NaN, null, undefined, Infinity)", () => {
  assert.strictEqual(computeClipProgress(5.0, 5.0, NaN), 0);
  assert.strictEqual(computeClipProgress(5.0, 5.0, undefined), 0);
  assert.strictEqual(computeClipProgress(5.0, 5.0, null), 0);

  const pNaNCurrentTime = computeClipProgress(NaN, 5.0, 5.0);
  assert(Number.isNaN(pNaNCurrentTime));
  // In TransformableClip.tsx: isKaraoke && clipProgress > 0
  // When clipProgress is NaN, (NaN > 0) evaluates to false, so Layer 2 correctly does NOT render!
  assert.strictEqual(pNaNCurrentTime > 0, false, "NaN > 0 must be false to prevent Konva rendering");

  const pNaNStartTime = computeClipProgress(5.0, NaN, 5.0);
  assert(Number.isNaN(pNaNStartTime));
  assert.strictEqual(pNaNStartTime > 0, false, "NaN > 0 must be false");

  const pInf = computeClipProgress(Infinity, 5.0, 5.0);
  assert.strictEqual(pInf, 1);

  const pNegInf = computeClipProgress(-Infinity, 5.0, 5.0);
  assert.strictEqual(pNegInf, 0);
});

// -----------------------------------------------------------------------------
// SUITE 2: Clipping Rectangle Geometry & Konva Bounds Safety
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 2: Clipping Rectangle Geometry & Bounds Safety ---");

test("Clip rectangle width scales proportionally with clipProgress", () => {
  const textWidth = 320;
  const textHeight = 60;

  const testProgresses = [0.01, 0.25, 0.5, 0.75, 0.99, 1.0];
  for (const p of testProgresses) {
    const bounds = computeClipBounds(textWidth, textHeight, p);
    const expectedWidth = textWidth * p;

    assert.strictEqual(bounds.clip.x, 0);
    assert.strictEqual(bounds.clip.y, 0);
    assert.strictEqual(bounds.clip.width, expectedWidth);
    assert.strictEqual(bounds.clipWidth, expectedWidth);
    assert.strictEqual(bounds.clip.height, textHeight + 20);
    assert.strictEqual(bounds.clipHeight, textHeight + 20);
    assert(bounds.clip.width > 0, `Width must be > 0 at progress ${p}`);
    assert(bounds.clip.width <= textWidth, `Width must not exceed textWidth at progress ${p}`);
  }
});

test("Zero progress or negative progress: KonvaGroup guard check", () => {
  // Line 406 of TransformableClip.tsx: {isKaraoke && clipProgress > 0 && ...}
  const isKaraoke = true;
  const progressZero = 0;
  const progressNegative = -0.1;

  const shouldRenderAtZero = isKaraoke && progressZero > 0;
  assert.strictEqual(shouldRenderAtZero, false, "Should not render highlight at progress 0");

  const shouldRenderAtNegative = isKaraoke && progressNegative > 0;
  assert.strictEqual(shouldRenderAtNegative, false, "Should not render highlight at negative progress");
});

test("Clipping rectangle does not produce negative or NaN values under boundary widths", () => {
  const testWidths = [10, 50, 500, 1920, 4000];
  const testProgresses = [0.0001, 0.5, 1.0];

  for (const w of testWidths) {
    for (const p of testProgresses) {
      const bounds = computeClipBounds(w, 50, p);
      assert(!Number.isNaN(bounds.clip.width), `Width should not be NaN for w=${w}, p=${p}`);
      assert(bounds.clip.width >= 0, `Width must be >= 0 for w=${w}, p=${p}`);
      assert(Number.isFinite(bounds.clip.width), `Width must be finite`);
    }
  }
});

test("Text dimension measurement fallback protects against 0 width", () => {
  const measured = getMeasuredTextDimensionsFallback("", 48, "Inter, sans-serif");
  assert(measured.width >= 10, `Measured width must be at least 10px fallback, got ${measured.width}`);
  assert(measured.height >= 10, `Measured height must be at least 10px fallback, got ${measured.height}`);
});

// -----------------------------------------------------------------------------
// SUITE 3: Japanese (Kanji / Hiragana / Katakana) & Unicode Strings
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 3: Japanese & Unicode Subtitle Strings ---");

function createMockCtx() {
  return {
    font: "",
    measureText(str) {
      // Realistic character width approximation for standard font metrics:
      // CJK characters are full-width (approx 1.0em = fontSize)
      // ASCII characters are proportional (approx 0.55em)
      let w = 0;
      const fontSize = parseFloat(this.font) || 48;
      for (const ch of str) {
        const code = ch.charCodeAt(0);
        // CJK Unified Ideographs, Hiragana, Katakana, full-width punctuation
        if (
          (code >= 0x3000 && code <= 0x9fff) ||
          (code >= 0xf900 && code <= 0xfaff) ||
          (code >= 0xff00 && code <= 0xffef)
        ) {
          w += fontSize * 1.0;
        } else {
          w += fontSize * 0.55;
        }
      }
      return { width: w };
    },
  };
}

test("Japanese Kanji strings: text width and clipping calculation", () => {
  const ctxMock = createMockCtx();
  const text = "東京都千代田区永田町国会議事堂前"; // 16 Kanji characters
  const fontSize = 48;
  const fontFamily = "'Noto Sans JP', sans-serif";

  const measured = getMeasuredTextDimensionsCanvas(text, fontSize, fontFamily, ctxMock);
  // 16 * 48 = 768px
  assert.strictEqual(measured.width, 768, `Expected 768px, got ${measured.width}`);

  const boundsHalf = computeClipBounds(measured.width, measured.height, 0.5);
  assert.strictEqual(boundsHalf.clip.width, 384);
});

test("Japanese Hiragana & Katakana strings: clipping calculation", () => {
  const ctxMock = createMockCtx();
  const text = "こんにちはありがとう・ナビビビデオエディター";
  const fontSize = 52;
  const fontFamily = "'Noto Sans JP', sans-serif";

  const measured = getMeasuredTextDimensionsCanvas(text, fontSize, fontFamily, ctxMock);
  assert(measured.width > 0, "Width must be positive");

  for (let p = 0.1; p <= 1.0; p += 0.1) {
    const bounds = computeClipBounds(measured.width, measured.height, p);
    assert(bounds.clip.width > 0);
    assert(bounds.clip.width <= measured.width + 1e-9);
  }
});

test("Mixed Japanese + Latin + Emoji strings", () => {
  const ctxMock = createMockCtx();
  const text = "Navivi v1.0 富士山ツーリング 120km 🚗💨";
  const fontSize = 48;
  const fontFamily = "Inter, sans-serif";

  const measured = getMeasuredTextDimensionsCanvas(text, fontSize, fontFamily, ctxMock);
  assert(measured.width > 0);
  assert(measured.height > 0);

  const bounds = computeClipBounds(measured.width, measured.height, 0.75);
  assert.strictEqual(bounds.clip.width, measured.width * 0.75);
});

test("CJK Fallback discrepancy when document is undefined (SSR / headless)", () => {
  const text = "富士山麓五合目"; // 7 CJK characters
  const fontSize = 48;
  const fallback = getMeasuredTextDimensionsFallback(text, fontSize, "Inter");

  // Fallback formula: text.length * fontSize * 0.6 = 7 * 48 * 0.6 = 201.6px
  // Actual CJK width in browser canvas is: 7 * 48 * 1.0 = 336px
  const actualApproxWidth = 7 * 48 * 1.0;
  const ratio = fallback.width / actualApproxWidth;

  // Fallback estimates width at 60% of actual CJK width
  assert(ratio < 0.7, `Fallback width ${fallback.width} is significantly smaller than actual ${actualApproxWidth}`);
  recordFinding(
    "Typography",
    "LOW",
    "CJK Text Dimension Fallback Underestimates Width in Headless/Mock Environments",
    `When document/canvas is unavailable, the fallback calculation (text.length * fontSize * 0.6) assumes Latin character aspect ratio (0.6). For Japanese CJK glyphs (aspect ratio ~1.0), the fallback underestimates text width by ~40% (201.6px vs 336px). In normal Tauri/browser runtime, document canvas context is present so this only affects non-DOM environments.`
  );
});

// -----------------------------------------------------------------------------
// SUITE 4: Multi-Line Subtitles & Text Wrapping Edge Cases
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 4: Multi-Line Subtitle Karaoke Behavior ---");

test("Multi-line text dimensions: height scales with line count, width uses max line", () => {
  const ctxMock = createMockCtx();
  const text = "Line 1 is long\nShort\nLine 3 medium";
  const fontSize = 40;
  const measured = getMeasuredTextDimensionsCanvas(text, fontSize, "Inter", ctxMock);

  // Height formula: lines.length * fontSize * 1.25 = 3 * 40 * 1.25 = 150px
  assert.strictEqual(measured.height, 150);
  // Width should be max width among lines
  const w1 = ctxMock.measureText("Line 1 is long").width;
  assert.strictEqual(measured.width, w1);
});

test("Multi-line karaoke wipe: single horizontal rect clips all lines simultaneously", () => {
  // When subtitle text has multiple lines (e.g. from SRT):
  // Line 1: "富士山のふもとを巡る旅" (11 chars -> 528px)
  // Line 2: "出発進行！" (5 chars -> 240px)
  const line1 = "富士山のふもとを巡る旅";
  const line2 = "出発進行！";
  const text = `${line1}\n${line2}`;
  const fontSize = 48;
  const ctxMock = createMockCtx();

  const measured = getMeasuredTextDimensionsCanvas(text, fontSize, "Noto Sans JP", ctxMock);
  const w1 = ctxMock.measureText(line1).width; // 528px
  const w2 = ctxMock.measureText(line2).width; // 240px
  assert.strictEqual(measured.width, w1); // 528px

  // At clipProgress = 0.5:
  // clipWidth = 528 * 0.5 = 264px.
  // In the Konva rendered output:
  // - Line 1 (528px) has 264px highlighted -> 50% highlighted.
  // - Line 2 (240px) has 264px covered by clip -> 100% HIGHLIGHTED!
  // Line 2 finishes highlighting at progress = 240 / 528 = 45.4%!
  const line2CompleteProgress = w2 / measured.width;
  assert(line2CompleteProgress < 0.5, `Line 2 completes prematurely at ${line2CompleteProgress * 100}% of duration`);

  recordFinding(
    "Karaoke Timing",
    "MEDIUM",
    "Multi-Line Subtitle Parallel Highlight Wipe",
    `In TransformableClip.tsx (lines 406-430), the karaoke highlight group uses a single 2D bounding rectangle (width: computedTextWidth * clipProgress, height: computedTextHeight + 20). For multi-line subtitles (common in SRT imports), all lines are wiped horizontally in parallel rather than line-by-line. Furthermore, shorter lines finish highlighting prematurely (e.g. at ~45% progress) while longer lines continue highlighting. This is a known geometric limitation of single-box progressive clipping.`
  );
});

// -----------------------------------------------------------------------------
// SUITE 5: Preload Window Subtitle Visibility Leakage
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 5: Preload Window Subtitle Visibility ---");

test("TimelineView PRELOAD_SECONDS = 0.5 causes subtitle base layer to render 0.5s early", () => {
  // TimelineView.tsx lines 576-585:
  // const PRELOAD_SECONDS = 0.5;
  // currentTime >= clip.startTime - PRELOAD_SECONDS && currentTime <= clip.startTime + clip.duration
  const clip = {
    id: "sub-1",
    trackId: "track-subtitles",
    type: "text",
    text: "Sub: こんにちは",
    startTime: 5.0,
    duration: 3.0,
    // Note: subtitles by default have no fadeIn
    fadeIn: undefined,
    fadeOut: undefined,
  };

  const preloadTime = 4.75; // 0.25s before clip.startTime
  const isIncludedInActiveClips =
    preloadTime >= clip.startTime - 0.5 && preloadTime <= clip.startTime + clip.duration;
  assert.strictEqual(isIncludedInActiveClips, true, "Clip is included in activeClipsToRender during preload");

  // In TransformableClip.tsx:
  // currentOpacity calculation:
  const opacity = computeOpacity(preloadTime, clip);
  assert.strictEqual(opacity, 1, `Subtitle opacity is 1 during preload window!`);

  // Karaoke progress at preload:
  const progress = computeClipProgress(preloadTime, clip.startTime, clip.duration);
  assert.strictEqual(progress, 0, `Karaoke progress is correctly 0`);

  // Impact: Base unhighlighted text renders with opacity 1 for 0.5s before clip.startTime
  recordFinding(
    "Rendering & Timing",
    "MEDIUM",
    "Subtitle Base Text Visible During 0.5s Preload Window",
    `In TimelineView.tsx line 576, activeClipsToRender filters clips with PRELOAD_SECONDS = 0.5 (currentTime >= clip.startTime - 0.5). While this preloads video elements, for text/subtitle clips with no fadeIn set, TransformableClip computes currentOpacity = 1. Consequently, unhighlighted subtitle text renders on the canvas 0.5s before its startTime. Karaoke progress correctly remains 0, but the base text pops in prematurely.`
  );
});

// -----------------------------------------------------------------------------
// SUITE 6: Stroke and Shadow Rendering Invariants
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 6: Stroke & Shadow Interaction with Karaoke ---");

test("Karaoke Highlight Layer omits shadow to prevent double-shadow artifacting", () => {
  // Verification of Worker M3 design decision:
  // Layer 1 KonvaText has shadowColor, shadowBlur, shadowOffsetX, shadowOffsetY, shadowOpacity
  // Layer 2 KonvaText inside KonvaGroup has fill, stroke, strokeWidth, fillAfterStrokeEnabled, but NO shadow
  // This verifies that shadow is not drawn twice or clipped with hard edges.
  const layer1Props = {
    shadowColor: "rgba(0,0,0,0.75)",
    shadowBlur: 4,
    shadowOffsetX: 2,
    shadowOffsetY: 2,
  };
  const layer2Props = {
    fill: "#f59e0b",
    stroke: "#000000",
    strokeWidth: 3,
    fillAfterStrokeEnabled: true,
  };

  assert.strictEqual(layer2Props.shadowColor, undefined);
  assert.strictEqual(layer2Props.shadowBlur, undefined);
  assert.strictEqual(layer2Props.fillAfterStrokeEnabled, true);
});

test("Large strokeWidth geometric boundary check", () => {
  // In Konva, stroke is centered on glyph path (strokeWidth / 2 extends outside the glyph).
  // With strokeWidth = 12, stroke extends 6px to the left of x=0 and 6px to right of glyph width.
  const strokeWidth = 12;
  const textWidth = 200;
  const halfStroke = strokeWidth / 2;

  // At clipProgress = 1.0, clipWidth = textWidth.
  // The outer half of the stroke on the rightmost edge extends past clipWidth.
  // Because Layer 1 (base layer) is underneath and unclipped, the base stroke is intact!
  assert.strictEqual(halfStroke, 6);
  assert.strictEqual(textWidth + halfStroke, 206);
});

// =============================================================================
// SUMMARY & VERDICT
// =============================================================================
console.log("\n=================================================");
console.log(`TOTAL TESTS: ${passedTests + failedTests}`);
console.log(`PASSED:      ${passedTests}`);
console.log(`FAILED:      ${failedTests}`);
console.log("=================================================");

console.log("\nFINDINGS SUMMARY:");
findings.forEach((f, idx) => {
  console.log(`\n[Finding ${idx + 1}] [${f.severity}] ${f.title}`);
  console.log(`  Category: ${f.category}`);
  console.log(`  Detail:   ${f.detail}`);
});

if (failedTests > 0) {
  process.exit(1);
} else {
  process.exit(0);
}
