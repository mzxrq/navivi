import { chromium } from "@playwright/test";
const out = process.argv[2];
const sizes = [[1000, 600], [1100, 800], [1000, 1000], [1280, 720], [1440, 900], [1920, 1080]];
const browser = await chromium.launch();
for (const [w, h] of sizes) {
  for (const state of ["generating", "error"]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    page.on("pageerror", (e) => console.log("pageerror", w, h, e.message.slice(0, 120)));
    await page.goto("http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html");
    await page.waitForTimeout(1500);
    await page.evaluate((state) => {
      for (let i = 0; i < 40; i++) window.__emit("render-log", `[00:${String(i).padStart(2, "0")}] [2/8] Generating TTS narration... waypoint ${i}/40 with a fairly long log line to test wrapping behaviour`);
      if (state === "error") { window.__emit("render-error", "[ERROR] FileNotFoundError: C:/Users/someone/Documents/Navivi/Workspaces/very_long_project_name/assets/audio/waypoint_03.wav"); window.__emit("render-finish", "Failed"); }
    }, state);
    await page.waitForTimeout(700);
    // Measure the modal cards against the unobstructed area (below TitleBar, above StatusBar).
    const r = await page.evaluate(() => {
      const cards = [...document.querySelectorAll(".pointer-events-auto.rounded-2xl")].map((e) => e.getBoundingClientRect());
      const top = 40, bottom = innerHeight - 28;
      return { cards: cards.map((c) => [Math.round(c.top), Math.round(c.bottom), Math.round(c.left), Math.round(c.right)]),
        ok: cards.length > 0 && cards.every((c) => c.top >= top && c.bottom <= bottom && c.left >= 0 && c.right <= innerWidth) };
    });
    console.log(`${w}x${h} ${state}: ${r.ok ? "FITS" : "OVERFLOW"} ${JSON.stringify(r.cards)}`);
    await page.screenshot({ path: `${out}/${w}x${h}-${state}.png` });
    await page.close();
  }
}
await browser.close();
