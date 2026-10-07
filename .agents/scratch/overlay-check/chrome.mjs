// Title bar, status bar, settings dialog and map toolbar screenshots.
import { chromium } from "@playwright/test";
const [out, theme = "light", locale = "en"] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
page.on("pageerror", (e) => console.log("pageerror", e.message));
await page.goto(`http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html?theme=${theme}&locale=${locale}&stops=demo&render=0`);
await page.waitForTimeout(3000);
const s = (n, clip) => page.screenshot({ path: `${out}/${theme}-${locale}-${n}.png`, ...(clip ? { clip } : {}) });
await page.keyboard.press("p"); await page.waitForTimeout(200);
await s("top", { x: 0, y: 0, width: 1280, height: 140 });
await page.keyboard.press("v");
await page.getByRole("button", { name: /^(Menu|メニュー)$/ }).click(); await page.waitForTimeout(250);
await s("menu", { x: 0, y: 0, width: 420, height: 440 });
await page.keyboard.press("Escape");
await page.getByRole("button", { name: /Undo|元に戻す/ }).hover(); await page.waitForTimeout(700);
await s("undo-tip", { x: 0, y: 0, width: 300, height: 90 });
await page.getByRole("button", { name: /History|履歴/ }).click(); await page.waitForTimeout(300);
await s("history", { x: 780, y: 380, width: 500, height: 420 });
await page.getByRole("button", { name: /System Logs|システム/ }).click(); await page.waitForTimeout(300);
await s("notifs", { x: 780, y: 380, width: 500, height: 420 });
await page.keyboard.press("Escape");
await s("status", { x: 0, y: 760, width: 1280, height: 40 });
await page.getByRole("button", { name: /App Settings|アプリ設定|設定/ }).first().click(); await page.waitForTimeout(400);
await s("settings-general");
for (const [i, n] of ["appearance", "api", "video", "pron"].entries()) {
  await page.getByRole("tab").nth(i + 1 + 2).click().catch(() => {});
}
const tabs = page.locator('[role="dialog"] [role="tab"]');
const count = await tabs.count();
for (let i = 1; i < count; i++) { await tabs.nth(i).click(); await page.waitForTimeout(250); await s(`settings-${i}`); }
await page.setViewportSize({ width: 1000, height: 680 }); await page.waitForTimeout(400);
await tabs.nth(3).click(); await page.waitForTimeout(250);
await s("settings-small");
await browser.close();
