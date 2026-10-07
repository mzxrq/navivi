import { chromium } from "@playwright/test";
const [out] = process.argv.slice(2);
const browser = await chromium.launch();
for (const [theme, locale] of [["light", "ja"], ["dark", "en"]]) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });
  page.on("pageerror", (e) => console.log("pageerror", e.message));
  await page.goto(`http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html?theme=${theme}&locale=${locale}&stops=demo&render=0`);
  await page.waitForTimeout(2200);
  const clip = { x: 0, y: 40, width: 360, height: 780 };
  await page.screenshot({ path: `${out}/s-${theme}-base.png`, clip });
  // Mode menu on the 2nd leg (below 三段壁展望台).
  await page.locator('button[aria-haspopup="menu"]').nth(1).click();
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${out}/s-${theme}-menu.png`, clip: { x: 0, y: 150, width: 360, height: 330 } });
  await page.keyboard.press("Escape");
  // Intro expanded.
  await page.locator('section button[aria-expanded]').first().click();
  await page.waitForTimeout(250);
  await page.screenshot({ path: `${out}/s-${theme}-intro.png`, clip });
  await page.locator('section button[aria-expanded]').first().click();
  // Edit mode + clear confirm.
  await page.getByRole("button", { name: locale === "ja" ? "編集" : "Edit", exact: true }).click();
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${out}/s-${theme}-edit.png`, clip });
  await page.getByRole("button", { name: /Clear route|ルートを消去|ルートをクリア/ }).click().catch(() => console.log("no clear btn"));
  await page.waitForTimeout(200);
  await page.screenshot({ path: `${out}/s-${theme}-clear.png`, clip: { x: 0, y: 760, width: 360, height: 70 } });
  await page.close();
}
await browser.close();
