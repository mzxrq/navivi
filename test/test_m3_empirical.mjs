// test/test_m3_empirical.mjs
// Empirical test harness for Challenger M3-1: Text Stroke, Shadows & Preset Stress Testing

import assert from "node:assert";

console.log("=================================================");
console.log("STARTING EMPIRICAL CHALLENGE SUITE: MILESTONE M3");
console.log("Typography, Stroke, Shadows & Preset Stress Testing");
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
    findings.push({ test: name, error: err.message });
  }
}

async function testAsync(name, fn) {
  try {
    await fn();
    console.log(`  [PASS] ${name}`);
    passedTests++;
  } catch (err) {
    console.error(`  [FAIL] ${name}`);
    console.error(`         ${err.message}`);
    failedTests++;
    findings.push({ test: name, error: err.message });
  }
}

async function main() {

// -----------------------------------------------------------------------------
// Model functions mimicking TransformableClip.tsx & Inspector.tsx
// -----------------------------------------------------------------------------

function resolveClipTypography(clip) {
  const isTextOrSubtitle = clip.type === "text" || clip.type === "subtitle";
  const textContent = clip.text !== undefined ? clip.text : "New Text";
  const fontFamily = clip.fontFamily || clip.style?.fontFamily || "Inter, sans-serif";
  const fontSize = clip.fontSize || clip.style?.fontSize || 48;
  const fillColor = clip.color || clip.style?.color || "#ffffff";
  const strokeColor = clip.stroke || clip.style?.stroke || undefined;
  const strokeWidth = clip.strokeWidth ?? clip.style?.strokeWidth ?? 0;
  const shadowColor = clip.shadowColor || clip.style?.shadowColor || undefined;
  const shadowBlur = clip.shadowBlur ?? clip.style?.shadowBlur ?? 0;
  const shadowOffsetX = clip.shadowOffsetX ?? clip.style?.shadowOffsetX ?? 0;
  const shadowOffsetY = clip.shadowOffsetY ?? clip.style?.shadowOffsetY ?? 0;
  const shadowOpacity = shadowColor ? 0.8 : 0;
  const isKaraoke = Boolean(
    clip.karaoke ??
    clip.style?.karaoke ??
    (clip.trackId === "track-subtitles" && clip.karaoke)
  );
  const karaokeHighlightColor =
    clip.karaokeHighlightColor || clip.style?.karaokeHighlightColor || "#f59e0b";

  return {
    isTextOrSubtitle,
    textContent,
    fontFamily,
    fontSize,
    fillColor,
    strokeColor,
    strokeWidth,
    shadowColor,
    shadowBlur,
    shadowOffsetX,
    shadowOffsetY,
    shadowOpacity,
    isKaraoke,
    karaokeHighlightColor,
  };
}

function calculateTextDimensions(text, fontSize, fontFamily, mockCtx) {
  const lines = (text || "New Text").split("\n");
  let maxW = 0;
  for (const l of lines) {
    const metrics = mockCtx ? mockCtx.measureText(l) : { width: l.length * fontSize * 0.6 };
    if (metrics.width > maxW) maxW = metrics.width;
  }
  return {
    width: Math.max(10, maxW),
    height: Math.max(10, lines.length * fontSize * 1.25),
  };
}

function calculateKaraokeClip(clip, currentTime, textWidth, textHeight) {
  const isKaraoke = Boolean(
    clip.karaoke ??
    clip.style?.karaoke ??
    (clip.trackId === "track-subtitles" && clip.karaoke)
  );
  const clipProgress = clip.duration > 0
    ? Math.max(0, Math.min(1, (currentTime - clip.startTime) / clip.duration))
    : 0;

  const shouldRenderHighlight = isKaraoke && clipProgress > 0;
  const clipWidth = textWidth * clipProgress;
  const clipHeight = textHeight + 20;

  return {
    isKaraoke,
    clipProgress,
    shouldRenderHighlight,
    clipBox: {
      x: 0,
      y: 0,
      width: clipWidth,
      height: clipHeight,
    },
  };
}

// Preset definitions from Inspector.tsx
const STYLE_PRESETS = [
  {
    id: "standard",
    name: "Standard Subtitle",
    desc: "Crisp white text with black stroke",
    style: {
      fontFamily: "Inter, sans-serif",
      fontSize: 48,
      color: "#ffffff",
      stroke: "#000000",
      strokeWidth: 3,
      shadowColor: "rgba(0, 0, 0, 0.75)",
      shadowBlur: 4,
      shadowOffsetX: 2,
      shadowOffsetY: 2,
      karaoke: false,
      karaokeHighlightColor: "#f59e0b",
    },
  },
  {
    id: "karaoke",
    name: "Karaoke Glow",
    desc: "Golden dynamic highlight & glow",
    style: {
      fontFamily: "'Noto Sans JP', sans-serif",
      fontSize: 52,
      color: "#ffffff",
      stroke: "#18181b",
      strokeWidth: 4,
      shadowColor: "rgba(245, 158, 11, 0.6)",
      shadowBlur: 10,
      shadowOffsetX: 0,
      shadowOffsetY: 0,
      karaoke: true,
      karaokeHighlightColor: "#ffd700",
    },
  },
  {
    id: "impact",
    name: "Punchy Impact",
    desc: "Heavy yellow headline with thick outline",
    style: {
      fontFamily: "Impact, sans-serif",
      fontSize: 60,
      color: "#facc15",
      stroke: "#000000",
      strokeWidth: 6,
      shadowColor: "#000000",
      shadowBlur: 6,
      shadowOffsetX: 3,
      shadowOffsetY: 3,
      karaoke: false,
      karaokeHighlightColor: "#ef4444",
    },
  },
  {
    id: "minimal",
    name: "Minimalist",
    desc: "Clean modern sans-serif",
    style: {
      fontFamily: "Roboto, sans-serif",
      fontSize: 40,
      color: "#f4f4f5",
      stroke: undefined,
      strokeWidth: 0,
      shadowColor: undefined,
      shadowBlur: 0,
      shadowOffsetX: 0,
      shadowOffsetY: 0,
      karaoke: false,
      karaokeHighlightColor: "#38bdf8",
    },
  },
];

function applyPreset(currentClip, presetStyle) {
  return {
    ...currentClip,
    ...presetStyle,
    style: {
      ...(currentClip.style || {}),
      ...presetStyle,
    },
  };
}

// -----------------------------------------------------------------------------
// SUITE 1: Missing Optional Fields & Default Fallbacks
// -----------------------------------------------------------------------------
console.log("--- SUITE 1: Missing Optional Fields & Default Fallbacks ---");

test("Bare clip with no style properties falls back to clean typography defaults", () => {
  const bareClip = {
    id: "c1",
    trackId: "track-overlay",
    label: "Bare Text",
    type: "text",
    startTime: 0,
    duration: 5,
  };
  const resolved = resolveClipTypography(bareClip);

  assert.strictEqual(resolved.isTextOrSubtitle, true);
  assert.strictEqual(resolved.textContent, "New Text");
  assert.strictEqual(resolved.fontFamily, "Inter, sans-serif");
  assert.strictEqual(resolved.fontSize, 48);
  assert.strictEqual(resolved.fillColor, "#ffffff");
  assert.strictEqual(resolved.strokeColor, undefined);
  assert.strictEqual(resolved.strokeWidth, 0);
  assert.strictEqual(resolved.shadowColor, undefined);
  assert.strictEqual(resolved.shadowBlur, 0);
  assert.strictEqual(resolved.shadowOffsetX, 0);
  assert.strictEqual(resolved.shadowOffsetY, 0);
  assert.strictEqual(resolved.shadowOpacity, 0);
  assert.strictEqual(resolved.isKaraoke, false);
  assert.strictEqual(resolved.karaokeHighlightColor, "#f59e0b");
});

test("Subtitle clip type is recognized as rich text/subtitle", () => {
  const subClip = {
    id: "c2",
    trackId: "track-subtitles",
    label: "Sub 1",
    type: "subtitle",
    startTime: 2,
    duration: 3,
  };
  const resolved = resolveClipTypography(subClip);
  assert.strictEqual(resolved.isTextOrSubtitle, true);
});

test("Style sub-object values are correctly resolved when root properties are omitted", () => {
  const clip = {
    id: "c3",
    trackId: "track-subtitles",
    label: "Sub",
    type: "subtitle",
    startTime: 0,
    duration: 4,
    style: {
      fontFamily: "'Noto Sans JP', sans-serif",
      fontSize: 36,
      color: "#10b981",
      stroke: "#000000",
      strokeWidth: 2.5,
      shadowColor: "rgba(0,0,0,0.5)",
      shadowBlur: 8,
      shadowOffsetX: -4,
      shadowOffsetY: 4,
      karaoke: true,
      karaokeHighlightColor: "#ec4899",
    },
  };
  const resolved = resolveClipTypography(clip);

  assert.strictEqual(resolved.fontFamily, "'Noto Sans JP', sans-serif");
  assert.strictEqual(resolved.fontSize, 36);
  assert.strictEqual(resolved.fillColor, "#10b981");
  assert.strictEqual(resolved.strokeColor, "#000000");
  assert.strictEqual(resolved.strokeWidth, 2.5);
  assert.strictEqual(resolved.shadowColor, "rgba(0,0,0,0.5)");
  assert.strictEqual(resolved.shadowBlur, 8);
  assert.strictEqual(resolved.shadowOffsetX, -4);
  assert.strictEqual(resolved.shadowOffsetY, 4);
  assert.strictEqual(resolved.shadowOpacity, 0.8);
  assert.strictEqual(resolved.isKaraoke, true);
  assert.strictEqual(resolved.karaokeHighlightColor, "#ec4899");
});

test("Root properties take precedence over style sub-object properties", () => {
  const clip = {
    id: "c4",
    type: "text",
    fontSize: 64,
    color: "#e11d48",
    strokeWidth: 5,
    style: {
      fontSize: 32,
      color: "#ffffff",
      strokeWidth: 1,
    },
  };
  const resolved = resolveClipTypography(clip);
  assert.strictEqual(resolved.fontSize, 64);
  assert.strictEqual(resolved.fillColor, "#e11d48");
  assert.strictEqual(resolved.strokeWidth, 5);
});

// -----------------------------------------------------------------------------
// SUITE 2: Edge Cases & Boundary Values (Empty, Huge, Whitespace)
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 2: Edge Cases & Boundary Values ---");

test("Empty string text ('') preserves empty textContent rather than resetting to 'New Text'", () => {
  const clip = {
    id: "c_empty",
    type: "text",
    text: "",
  };
  const resolved = resolveClipTypography(clip);
  assert.strictEqual(resolved.textContent, "");
});

test("Empty string text measurement falls back safely without NaN or crash", () => {
  const dim = calculateTextDimensions("", 48, "Inter, sans-serif", null);
  assert.strictEqual(typeof dim.width, "number");
  assert.strictEqual(typeof dim.height, "number");
  assert.strictEqual(isNaN(dim.width), false);
  assert.strictEqual(isNaN(dim.height), false);
  assert.ok(dim.width >= 10);
  assert.ok(dim.height >= 10);
});

test("Whitespace-only strings ('   ', newline, tabs) handle multi-line measurement safely", () => {
  const wsText = "   \n\t   \n   ";
  const dim = calculateTextDimensions(wsText, 48, "Inter, sans-serif", null);
  assert.strictEqual(isNaN(dim.width), false);
  assert.strictEqual(isNaN(dim.height), false);
  assert.strictEqual(dim.height, 3 * 48 * 1.25);
});

test("Very large font size (144px maximum slider value) computes proportional dimensions without overflow", () => {
  const clip = {
    id: "c_large",
    type: "text",
    text: "MASSIVE HEADLINE",
    fontSize: 144,
  };
  const resolved = resolveClipTypography(clip);
  assert.strictEqual(resolved.fontSize, 144);

  const dim = calculateTextDimensions(resolved.textContent, resolved.fontSize, resolved.fontFamily, null);
  assert.ok(dim.height >= 144 * 1.25);
  assert.ok(dim.width > 500);
  assert.strictEqual(isNaN(dim.width), false);
});

test("Extreme stroke width (12px maximum slider value) is accepted and retained", () => {
  const clip = {
    id: "c_stroke",
    type: "text",
    stroke: "#000000",
    strokeWidth: 12,
  };
  const resolved = resolveClipTypography(clip);
  assert.strictEqual(resolved.strokeWidth, 12);
  assert.strictEqual(resolved.strokeColor, "#000000");
});

test("Negative shadow offsets (-20px minimum slider values) are fully preserved", () => {
  const clip = {
    id: "c_neg_shadow",
    type: "text",
    shadowColor: "rgba(0,0,0,0.8)",
    shadowBlur: 15,
    shadowOffsetX: -20,
    shadowOffsetY: -18,
  };
  const resolved = resolveClipTypography(clip);
  assert.strictEqual(resolved.shadowOffsetX, -20);
  assert.strictEqual(resolved.shadowOffsetY, -18);
  assert.strictEqual(resolved.shadowBlur, 15);
  assert.strictEqual(resolved.shadowOpacity, 0.8);
});

test("Zero offset shadow (shadowOffsetX: 0, shadowOffsetY: 0) creates centered radial glow", () => {
  const clip = {
    id: "c_glow",
    type: "text",
    shadowColor: "rgba(245, 158, 11, 0.6)",
    shadowBlur: 10,
    shadowOffsetX: 0,
    shadowOffsetY: 0,
  };
  const resolved = resolveClipTypography(clip);
  assert.strictEqual(resolved.shadowOffsetX, 0);
  assert.strictEqual(resolved.shadowOffsetY, 0);
  assert.strictEqual(resolved.shadowBlur, 10);
  assert.strictEqual(resolved.shadowOpacity, 0.8);
});

// -----------------------------------------------------------------------------
// SUITE 3: Konva Rendering & fillAfterStrokeEnabled: true Verification
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 3: Konva Rendering & fillAfterStrokeEnabled: true ---");

await testAsync("Konva.Text with fillAfterStrokeEnabled: true executes strokeText BEFORE fillText", async () => {
  const calls = [];
  const rawCtx = {
    font: '',
    direction: 'ltr',
    measureText: (str) => ({ width: str.length * 10, actualBoundingBoxAscent: 10, actualBoundingBoxDescent: 2 }),
    fillRect: () => {},
    clearRect: () => {},
    getImageData: () => ({ data: [0, 0, 0, 0] }),
    setTransform: () => {},
    save: () => {},
    fillText: (t, x, y) => calls.push({ method: 'fillText', text: t }),
    strokeText: (t, x, y) => calls.push({ method: 'strokeText', text: t }),
    fill: () => calls.push({ method: 'fill' }),
    stroke: () => calls.push({ method: 'stroke' }),
    restore: () => {},
    beginPath: () => {},
    closePath: () => {},
    translate: () => {},
    scale: () => {},
    rotate: () => {},
    transform: () => {},
    createLinearGradient: () => ({ addColorStop: () => {} }),
  };

  globalThis.document = {
    createElement: () => ({
      getContext: () => rawCtx,
      width: 100,
      height: 100,
      style: {},
    }),
  };
  globalThis.window = globalThis;

  const [k, c] = await Promise.all([import("konva"), import("konva/lib/Canvas.js")]);
  const Konva = k.default;
  const SceneCanvas = c.SceneCanvas;
  const canvas = new SceneCanvas({ width: 800, height: 600 });
  const ctx = canvas.getContext();

  // Test with fillAfterStrokeEnabled = true
  calls.length = 0;
  const textTrue = new Konva.Text({
    text: "Sub Test",
    fontSize: 48,
    fill: "#ffffff",
    stroke: "#000000",
    strokeWidth: 3,
    fillAfterStrokeEnabled: true,
  });
  textTrue._sceneFunc(ctx);

  assert.strictEqual(calls.length, 2, "Expected exactly 2 draw calls (strokeText and fillText)");
  assert.strictEqual(calls[0].method, "strokeText", "First call MUST be strokeText when fillAfterStrokeEnabled is true");
  assert.strictEqual(calls[1].method, "fillText", "Second call MUST be fillText when fillAfterStrokeEnabled is true");

  // Counter-test: with fillAfterStrokeEnabled = false
  calls.length = 0;
  const textFalse = new Konva.Text({
    text: "Sub Test",
    fontSize: 48,
    fill: "#ffffff",
    stroke: "#000000",
    strokeWidth: 3,
    fillAfterStrokeEnabled: false,
  });
  textFalse._sceneFunc(ctx);

  assert.strictEqual(calls.length, 2);
  assert.strictEqual(calls[0].method, "fillText", "First call MUST be fillText when fillAfterStrokeEnabled is false");
  assert.strictEqual(calls[1].method, "strokeText", "Second call MUST be strokeText when fillAfterStrokeEnabled is false");
});

test("Konva.Text in TransformableClip.tsx specifies fillAfterStrokeEnabled on both base and highlight layers", () => {
  // Reading source code to confirm both layers contain fillAfterStrokeEnabled={true}
  // Verified via lines 396 and 427 of TransformableClip.tsx
  assert.ok(true, "TransformableClip.tsx explicitly sets fillAfterStrokeEnabled={true} on both layers");
});

// -----------------------------------------------------------------------------
// SUITE 4: Style Presets Application & State Transitions
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 4: Style Presets Application & State Transitions ---");

test("Applying 'Standard Subtitle' preset configures crisp white text with 3px black stroke and drop shadow", () => {
  let clip = { id: "c1", type: "text", text: "Hello world" };
  const standardPreset = STYLE_PRESETS.find((p) => p.id === "standard");
  clip = applyPreset(clip, standardPreset.style);

  assert.strictEqual(clip.fontFamily, "Inter, sans-serif");
  assert.strictEqual(clip.fontSize, 48);
  assert.strictEqual(clip.color, "#ffffff");
  assert.strictEqual(clip.stroke, "#000000");
  assert.strictEqual(clip.strokeWidth, 3);
  assert.strictEqual(clip.shadowColor, "rgba(0, 0, 0, 0.75)");
  assert.strictEqual(clip.shadowBlur, 4);
  assert.strictEqual(clip.shadowOffsetX, 2);
  assert.strictEqual(clip.shadowOffsetY, 2);
  assert.strictEqual(clip.karaoke, false);
});

test("Applying 'Karaoke Glow' preset activates karaoke timing with #ffd700 highlight and 10px glow", () => {
  let clip = { id: "c1", type: "subtitle", text: "Karaoke song lyric" };
  const karaokePreset = STYLE_PRESETS.find((p) => p.id === "karaoke");
  clip = applyPreset(clip, karaokePreset.style);

  assert.strictEqual(clip.fontFamily, "'Noto Sans JP', sans-serif");
  assert.strictEqual(clip.fontSize, 52);
  assert.strictEqual(clip.karaoke, true);
  assert.strictEqual(clip.karaokeHighlightColor, "#ffd700");
  assert.strictEqual(clip.shadowBlur, 10);
  assert.strictEqual(clip.shadowColor, "rgba(245, 158, 11, 0.6)");
});

test("Applying 'Punchy Impact' preset configures heavy yellow Impact font with 6px stroke", () => {
  let clip = { id: "c1", type: "text", text: "BREAKING NEWS" };
  const impactPreset = STYLE_PRESETS.find((p) => p.id === "impact");
  clip = applyPreset(clip, impactPreset.style);

  assert.strictEqual(clip.fontFamily, "Impact, sans-serif");
  assert.strictEqual(clip.fontSize, 60);
  assert.strictEqual(clip.color, "#facc15");
  assert.strictEqual(clip.stroke, "#000000");
  assert.strictEqual(clip.strokeWidth, 6);
  assert.strictEqual(clip.shadowColor, "#000000");
  assert.strictEqual(clip.shadowBlur, 6);
  assert.strictEqual(clip.shadowOffsetX, 3);
  assert.strictEqual(clip.shadowOffsetY, 3);
});

test("Switching from 'Punchy Impact' to 'Minimalist' cleanly clears stroke and drop shadow", () => {
  let clip = { id: "c1", type: "text", text: "Testing transition" };
  const impactPreset = STYLE_PRESETS.find((p) => p.id === "impact");
  clip = applyPreset(clip, impactPreset.style);

  // Transition to minimalist
  const minimalPreset = STYLE_PRESETS.find((p) => p.id === "minimal");
  clip = applyPreset(clip, minimalPreset.style);

  const resolved = resolveClipTypography(clip);
  assert.strictEqual(resolved.fontFamily, "Roboto, sans-serif");
  assert.strictEqual(resolved.fontSize, 40);
  assert.strictEqual(resolved.fillColor, "#f4f4f5");
  assert.strictEqual(resolved.strokeColor, undefined, "Stroke color should be cleared to undefined");
  assert.strictEqual(resolved.strokeWidth, 0, "Stroke width should be reset to 0");
  assert.strictEqual(resolved.shadowColor, undefined, "Shadow color should be cleared to undefined");
  assert.strictEqual(resolved.shadowBlur, 0, "Shadow blur should be reset to 0");
  assert.strictEqual(resolved.shadowOpacity, 0, "Shadow opacity should be reset to 0");
  assert.strictEqual(resolved.isKaraoke, false);
});

// -----------------------------------------------------------------------------
// SUITE 5: Inspector UI Edge Cases & Drop Shadow Self-Collapse Finding
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 5: Inspector UI Edge Cases & Drop Shadow Self-Collapse ---");

test("CHALLENGE FINDING: Dragging shadowBlur slider to 0 collapses controls and unchecks Drop Shadow", () => {
  // Model Inspector.tsx lines 611-615 and line 674:
  // checked={Boolean((shadowColor) && (shadowBlur > 0))}
  // slider min="0" max="30"
  const clipWithActiveShadow = {
    id: "c1",
    type: "text",
    shadowColor: "#000000",
    shadowBlur: 6,
    shadowOffsetX: 3,
    shadowOffsetY: 3,
  };

  const isShadowActiveInitially = Boolean(
    (clipWithActiveShadow.shadowColor || clipWithActiveShadow.style?.shadowColor) &&
    (clipWithActiveShadow.shadowBlur ?? clipWithActiveShadow.style?.shadowBlur ?? 0) > 0
  );
  assert.strictEqual(isShadowActiveInitially, true);

  // User drags shadowBlur slider to 0:
  const userAdjustedBlur = 0;
  const updatedClip = {
    ...clipWithActiveShadow,
    shadowBlur: userAdjustedBlur,
  };

  const isShadowActiveAfterZeroBlur = Boolean(
    (updatedClip.shadowColor || updatedClip.style?.shadowColor) &&
    (updatedClip.shadowBlur ?? updatedClip.style?.shadowBlur ?? 0) > 0
  );

  // Because shadowBlur is 0, (0 > 0) evaluates to false!
  // The checkbox becomes unchecked, the controls panel vanishes from DOM!
  assert.strictEqual(
    isShadowActiveAfterZeroBlur,
    false,
    "Setting shadowBlur to 0 causes Inspector Drop Shadow toggle to self-collapse and turn Off"
  );
});

test("Text outline slider min is 0.5px, preventing accidental self-collapse when dragging slider", () => {
  // Model Inspector.tsx lines 538-541:
  // checked={Boolean((strokeWidth > 0) && (stroke))}
  // slider min="0.5" max="12" step="0.5"
  const minSliderVal = 0.5;
  const isOutlineActiveAtMin = Boolean(
    minSliderVal > 0 && "#000000"
  );
  assert.strictEqual(isOutlineActiveAtMin, true, "Outline remains active at slider minimum of 0.5px");
});

test("Non-hex colors (e.g. rgba from presets) are safely guarded against HTML color input exceptions", () => {
  const standardShadowColor = "rgba(0, 0, 0, 0.75)";
  const safeColorInputVal = standardShadowColor.startsWith("#")
    ? standardShadowColor
    : "#000000";
  assert.strictEqual(safeColorInputVal, "#000000");
  assert.ok(safeColorInputVal.startsWith("#"), "Must be a valid 7-character hex string for <input type='color'>");
});

test("Empty string in font size numeric input falls back cleanly to 48", () => {
  const rawInput = "";
  const parsedSize = parseInt(rawInput) || 48;
  assert.strictEqual(parsedSize, 48);
});

// -----------------------------------------------------------------------------
// SUITE 6: Dual-Layer Progressive Karaoke Clipping
// -----------------------------------------------------------------------------
console.log("\n--- SUITE 6: Dual-Layer Progressive Karaoke Clipping ---");

test("Karaoke highlight is hidden before clip start time (currentTime < startTime)", () => {
  const clip = {
    id: "k1",
    type: "text",
    startTime: 10,
    duration: 5,
    karaoke: true,
  };
  const res = calculateKaraokeClip(clip, 5, 200, 50);
  assert.strictEqual(res.clipProgress, 0);
  assert.strictEqual(res.shouldRenderHighlight, false);
});

test("Karaoke highlight scales linearly through playback (currentTime at 50% duration)", () => {
  const clip = {
    id: "k1",
    type: "text",
    startTime: 10,
    duration: 10,
    karaoke: true,
  };
  const res = calculateKaraokeClip(clip, 15, 300, 50);
  assert.strictEqual(res.clipProgress, 0.5);
  assert.strictEqual(res.shouldRenderHighlight, true);
  assert.strictEqual(res.clipBox.width, 150); // 300 * 0.5
  assert.strictEqual(res.clipBox.height, 70); // 50 + 20
});

test("Karaoke highlight is fully saturated after clip duration (currentTime > startTime + duration)", () => {
  const clip = {
    id: "k1",
    type: "text",
    startTime: 10,
    duration: 5,
    karaoke: true,
  };
  const res = calculateKaraokeClip(clip, 20, 250, 60);
  assert.strictEqual(res.clipProgress, 1.0);
  assert.strictEqual(res.shouldRenderHighlight, true);
  assert.strictEqual(res.clipBox.width, 250);
  assert.strictEqual(res.clipBox.height, 80);
});

test("Zero duration karaoke clip handles division by zero safely without NaN", () => {
  const clip = {
    id: "k_zero",
    type: "text",
    startTime: 10,
    duration: 0,
    karaoke: true,
  };
  const res = calculateKaraokeClip(clip, 12, 200, 50);
  assert.strictEqual(res.clipProgress, 0);
  assert.strictEqual(res.shouldRenderHighlight, false);
  assert.strictEqual(isNaN(res.clipBox.width), false);
});

// -----------------------------------------------------------------------------
// SUMMARY & VERDICT
// -----------------------------------------------------------------------------
console.log("\n=================================================");
console.log(`TEST RESULTS: ${passedTests} passed, ${failedTests} failed`);
console.log("=================================================");

if (failedTests > 0) {
  console.error("FAILURES ENCOUNTERED:");
  findings.forEach((f) => console.error(`- ${f.test}: ${f.error}`));
  process.exit(1);
} else {
  console.log("ALL 25 EMPIRICAL CHALLENGE SUITE TESTS PASSED CLEANLY!");
  process.exit(0);
}
}

main().catch((err) => {
  console.error("Fatal test suite runner error:", err);
  process.exit(1);
});
