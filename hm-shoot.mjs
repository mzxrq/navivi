import { chromium } from "@playwright/test";
const [out, tag = "base", which = "hills"] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("pageerror", e.message));
page.on("console", (m) => { if (m.type() === "error") console.log("console.error", m.text().slice(0, 200)); });
await page.goto("http://127.0.0.1:5201/.agents/scratch/heatmap-check/index.html?theme=light&locale=en&render=0");
await page.waitForTimeout(2500);
for (const f of which.split(",")) {
  await page.evaluate((p) => window.__import(p), `C:/g/${f}.gpx`);
  await page.waitForTimeout(1500);
}
const info = await page.evaluate(() => ({
  wps: window.__ws.waypoints.map((w) => ({ n: w.name, mode: w.routeMode, cr: w.customRoute?.length, keys: Object.keys(w).filter((k) => /ele/i.test(k)) })),
  rp: window.__ws.routePoints.length, rp3: window.__ws.routePoints.filter((p) => p.length > 2).length,
}));
console.log(JSON.stringify(info));
await page.screenshot({ path: `${out}/${tag}-off.png` });
await page.evaluate(() => window.__ws.updateSettings({ show_route_heatmap: true }));
await page.waitForTimeout(2500);
await page.screenshot({ path: `${out}/${tag}-on.png` });
await browser.close();
