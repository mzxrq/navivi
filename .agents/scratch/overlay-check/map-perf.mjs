// Pans/zooms/rotates the map and reports frame times + long tasks.
// Usage (from repo root): node map-perf.mjs [label] [render=0|1]
import { chromium } from "@playwright/test";
const [label = "run", rendering = "0"] = process.argv.slice(2);
const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("pageerror", e.message));
await page.goto(`http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html?theme=light&locale=en&stops=demo&render=${rendering}`);
await page.waitForTimeout(5000);
await page.evaluate(() => {
  window.__perf = { frames: [], long: 0, longMs: 0 };
  new PerformanceObserver((l) => l.getEntries().forEach((e) => { __perf.long++; __perf.longMs += e.duration; })).observe({ type: "longtask" });
  let last = performance.now();
  const tick = (t) => { __perf.frames.push(t - last); last = t; __perf.raf = requestAnimationFrame(tick); };
  __perf.raf = requestAnimationFrame(tick);
});
const cx = 900, cy = 450;
for (let r = 0; r < 3; r++) {
  await page.mouse.move(cx, cy); await page.mouse.down();
  for (let i = 0; i < 30; i++) await page.mouse.move(cx - i * 8, cy - i * 4);
  await page.mouse.up();
  for (let i = 0; i < 6; i++) { await page.mouse.wheel(0, i % 2 ? 200 : -200); await page.waitForTimeout(60); }
  await page.mouse.move(cx, cy); await page.mouse.down({ button: "right" });
  for (let i = 0; i < 20; i++) await page.mouse.move(cx + i * 10, cy);
  await page.mouse.up({ button: "right" });
  await page.waitForTimeout(1500); // let moveend/idle work run
}
const res = await page.evaluate(() => {
  cancelAnimationFrame(__perf.raf);
  const f = __perf.frames.slice(1).sort((a, b) => a - b);
  const pct = (p) => f[Math.floor(f.length * p)].toFixed(1);
  return { frames: f.length, p50: pct(0.5), p95: pct(0.95), max: f[f.length - 1].toFixed(0), jank50: f.filter((x) => x > 50).length, longTasks: __perf.long, longMs: Math.round(__perf.longMs) };
});
console.log(label, JSON.stringify(res));
await browser.close();
