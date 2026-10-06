import { chromium } from "@playwright/test";
const out = process.argv[2];
const browser = await chromium.launch();
for (const [w, h, theme, locale] of [[1280, 900, "light", "ja"], [1000, 600, "light", "ja"], [1280, 900, "dark", "en"]]) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  await page.addInitScript(() => localStorage.clear());
  await page.goto(`http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html?theme=${theme}&locale=${locale}`);
  await page.waitForTimeout(1800);
  await page.screenshot({ path: `${out}/stepper-${w}x${h}-${theme}-${locale}.png`, clip: { x: 0, y: 40, width: w > 1100 ? 850 : w, height: 200 } });
  await page.close();
}
await browser.close();
