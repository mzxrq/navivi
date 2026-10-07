import { chromium } from "@playwright/test";
const [out, tag = "before"] = process.argv.slice(2);
const browser = await chromium.launch();
for (const [theme, locale] of [["light", "ja"], ["dark", "en"]]) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 } });
  page.on("pageerror", (e) => console.log("pageerror", e.message));
  await page.goto(`http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html?theme=${theme}&locale=${locale}&stops=demo&render=0`);
  await page.waitForTimeout(2200);
  await page.screenshot({ path: `${out}/sidebar-${tag}-${theme}.png`, clip: { x: 0, y: 0, width: 420, height: 860 } });
  // hover the 2nd stop to reveal hover affordances
  const item = page.getByText("三段壁展望台", { exact: true }).first();
  if (await item.count()) { await item.hover(); await page.waitForTimeout(300); await page.screenshot({ path: `${out}/sidebar-${tag}-${theme}-hover.png`, clip: { x: 0, y: 0, width: 420, height: 860 } }); }
  await page.close();
}
await browser.close();
