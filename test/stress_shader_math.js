// Mathematical & Boundary Verification for GLSL Transitions
// Verifies whether UV sampling coordinates stay within [0.0, 1.0]
// and checks behavior at progress = 0.0, 0.5, 1.0

function step(edge, x) {
  return x < edge ? 0.0 : 1.0;
}

function mix(a, b, t) {
  return a * (1.0 - t) + b * t;
}

function fract(x) {
  return x - Math.floor(x);
}

function sign(x) {
  return x < 0 ? -1 : (x > 0 ? 1 : 0);
}

const SHADER_EVALUATORS = {
  "glsl-crossfade": (uv, progress) => {
    // vec4 transition(vec2 uv) { return mix(getFromColor(uv), getToColor(uv), progress); }
    return {
      fromUV: uv,
      toUV: uv,
      weightTo: progress,
      outOfBoundsFrom: uv[0] < 0 || uv[0] > 1 || uv[1] < 0 || uv[1] > 1,
      outOfBoundsTo: uv[0] < 0 || uv[0] > 1 || uv[1] < 0 || uv[1] > 1,
    };
  },

  "glsl-wipe": (uv, progress) => {
    // vec4 transition(vec2 uv) { return mix(getFromColor(uv), getToColor(uv), step(uv.x, progress)); }
    const s = step(uv[0], progress);
    return {
      fromUV: uv,
      toUV: uv,
      weightTo: s,
      outOfBoundsFrom: false,
      outOfBoundsTo: false,
      isFrom: s === 0,
      isTo: s === 1,
    };
  },

  "glsl-slide": (uv, progress) => {
    // vec2 p = uv - vec2(progress, 0.0);
    // if (p.x >= 0.0) return getFromColor(p); else return getToColor(p + vec2(1.0, 0.0));
    const px = uv[0] - progress;
    const py = uv[1];
    if (px >= 0.0) {
      return {
        sampled: "from",
        uv: [px, py],
        outOfBounds: px < 0.0 || px > 1.0 || py < 0.0 || py > 1.0,
      };
    } else {
      const toUv = [px + 1.0, py];
      return {
        sampled: "to",
        uv: toUv,
        outOfBounds: toUv[0] < 0.0 || toUv[0] > 1.0 || toUv[1] < 0.0 || toUv[1] > 1.0,
      };
    }
  },

  "glsl-dissolve": (uv, progress) => {
    // float rand(vec2 co) { return fract(sin(dot(co.xy, vec2(12.9898, 78.233))) * 43758.5453); }
    // return mix(getFromColor(uv), getToColor(uv), step(r, progress));
    const dot = uv[0] * 12.9898 + uv[1] * 78.233;
    const r = fract(Math.sin(dot) * 43758.5453);
    const s = step(r, progress);
    return {
      fromUV: uv,
      toUV: uv,
      rand: r,
      weightTo: s,
      sampled: s === 1 ? "to" : "from"
    };
  }
};

const results = {};

// Test 1: Boundary values of progress = 0.0 and progress = 1.0
results["boundary_tests"] = {};

// Test glsl-crossfade
results["boundary_tests"]["glsl-crossfade"] = {
  at_progress_0: SHADER_EVALUATORS["glsl-crossfade"]([0.5, 0.5], 0.0).weightTo === 0.0,
  at_progress_1: SHADER_EVALUATORS["glsl-crossfade"]([0.5, 0.5], 1.0).weightTo === 1.0,
};

// Test glsl-wipe
// Check what happens across x in [0.0, 1.0] at progress = 0.0 and progress = 1.0
const wipe_prog0_x0 = SHADER_EVALUATORS["glsl-wipe"]([0.0, 0.5], 0.0);
const wipe_prog0_x_eps = SHADER_EVALUATORS["glsl-wipe"]([0.001, 0.5], 0.0);
const wipe_prog1_x1 = SHADER_EVALUATORS["glsl-wipe"]([1.0, 0.5], 1.0);
results["boundary_tests"]["glsl-wipe"] = {
  prog0_at_x0_returns_to: wipe_prog0_x0.isTo, // step(0.0, 0.0) = 1.0 -> TO!
  prog0_at_x_eps_returns_from: wipe_prog0_x_eps.isFrom, // step(0.001, 0.0) = 0.0 -> FROM
  prog1_at_x1_returns_to: wipe_prog1_x1.isTo, // step(1.0, 1.0) = 1.0 -> TO
  finding: wipe_prog0_x0.isTo ? "LEAK: At progress = 0.0 and uv.x = 0.0, step(0.0, 0.0) evaluates to 1.0, returning toColor on the left boundary!" : "OK"
};

// Test glsl-slide
// At progress = 0.0
const slide_prog0_x0 = SHADER_EVALUATORS["glsl-slide"]([0.0, 0.5], 0.0);
const slide_prog0_x1 = SHADER_EVALUATORS["glsl-slide"]([1.0, 0.5], 0.0);
// At progress = 1.0
const slide_prog1_x0 = SHADER_EVALUATORS["glsl-slide"]([0.0, 0.5], 1.0);
const slide_prog1_x1 = SHADER_EVALUATORS["glsl-slide"]([1.0, 0.5], 1.0); // exact edge uv.x = 1.0
const slide_prog1_x_near1 = SHADER_EVALUATORS["glsl-slide"]([0.9999, 0.5], 1.0);
results["boundary_tests"]["glsl-slide"] = {
  prog0_x0: slide_prog0_x0,
  prog0_x1: slide_prog0_x1,
  prog1_x0: slide_prog1_x0,
  prog1_x1: slide_prog1_x1,
  prog1_x_near1: slide_prog1_x_near1,
  finding: slide_prog1_x1.sampled === "from" ? "LEAK: At progress = 1.0 and uv.x = 1.0, px = 0.0, px >= 0.0 is true, returning fromColor(0, y) on the right edge!" : "OK"
};

// Test glsl-dissolve
// At progress = 0.0 and uv = [0.0, 0.0]
const dissolve_prog0_00 = SHADER_EVALUATORS["glsl-dissolve"]([0.0, 0.0], 0.0);
const dissolve_prog0_center = SHADER_EVALUATORS["glsl-dissolve"]([0.5, 0.5], 0.0);
const dissolve_prog1_center = SHADER_EVALUATORS["glsl-dissolve"]([0.5, 0.5], 1.0);
results["boundary_tests"]["glsl-dissolve"] = {
  prog0_at_origin: dissolve_prog0_00,
  prog0_at_center: dissolve_prog0_center,
  prog1_at_center: dissolve_prog1_center,
  finding: dissolve_prog0_00.sampled === "to" ? "LEAK: At progress = 0.0 and uv = (0,0), rand(0,0) = 0.0, step(0.0, 0.0) = 1.0, returning toColor at origin!" : "OK"
};

// Test 2: UV Coordinate Range Testing (Over 10,000 UV points across [0, 1] x [0, 1])
results["uv_range_tests"] = {};
for (const [name, fn] of Object.entries(SHADER_EVALUATORS)) {
  let minUvX = Infinity, maxUvX = -Infinity;
  let minUvY = Infinity, maxUvY = -Infinity;
  let oobCount = 0;

  for (let p = 0; p <= 1.0; p += 0.1) {
    for (let x = 0; x <= 1.0; x += 0.05) {
      for (let y = 0; y <= 1.0; y += 0.05) {
        const out = fn([x, y], p);
        const sampledUv = out.uv || out.fromUV;
        if (sampledUv) {
          minUvX = Math.min(minUvX, sampledUv[0]);
          maxUvX = Math.max(maxUvX, sampledUv[0]);
          minUvY = Math.min(minUvY, sampledUv[1]);
          maxUvY = Math.max(maxUvY, sampledUv[1]);
          if (sampledUv[0] < -1e-6 || sampledUv[0] > 1.000001 || sampledUv[1] < -1e-6 || sampledUv[1] > 1.000001) {
            oobCount++;
          }
        }
      }
    }
  }

  results["uv_range_tests"][name] = {
    minUvX: Math.round(minUvX * 1000) / 1000,
    maxUvX: Math.round(maxUvX * 1000) / 1000,
    minUvY: Math.round(minUvY * 1000) / 1000,
    maxUvY: Math.round(maxUvY * 1000) / 1000,
    outOfBoundsCount: oobCount,
    status: oobCount === 0 ? "PASSED (all UVs strictly in [0.0, 1.0])" : `FAILED (${oobCount} out-of-bounds UVs)`
  };
}

console.log(JSON.stringify(results, null, 2));
