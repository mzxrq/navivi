import { chromium } from "@playwright/test";
const [out, theme = "light", locale = "en"] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("pageerror", e.message));
await page.goto(`http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html?theme=${theme}&locale=${locale}&stops=demo&render=0`);
await page.waitForTimeout(3000);
const shot = (name, clip) => page.screenshot({ path: `${out}/m-${theme}-${name}.png`, ...(clip ? { clip } : {}) });
const pointCount = () => page.evaluate(() => document.querySelectorAll(".mapboxgl-marker .bg-amber-500, .mapboxgl-marker .bg-navi.ring-4").length);
const top = { x: 360, y: 40, width: 1080, height: 330 };

await shot("base", top);
await page.keyboard.press("p"); await page.waitForTimeout(200);
await shot("add", top);
await page.keyboard.press("v");
await page.getByRole("button", { name: /Layers|レイヤー/ }).click(); await page.waitForTimeout(400);
await shot("layers", { x: 1100, y: 40, width: 340, height: 420 });
await page.getByRole("button", { name: /Route Lines Config|ルート/ }).first().click(); await page.waitForTimeout(300);
await shot("style", { x: 1100, y: 40, width: 340, height: 520 });
await page.mouse.click(900, 600); // close popover

// Pencil with no leg selected.
await page.keyboard.press("l"); await page.waitForTimeout(250);
await shot("draw-noleg", top);
// Pick first leg from the draw bar's leg menu.
await page.locator('button[aria-haspopup="menu"]').filter({ hasText: /Choose a leg|区間を選択/ }).click();
await page.getByRole("menuitemradio").first().click();
await page.waitForTimeout(1200);
const mapBox = { x: 360, y: 40, w: 1080, h: 820 };
const at = (fx, fy) => [mapBox.x + mapBox.w * fx, mapBox.y + mapBox.h * fy];
for (const [fx, fy] of [[0.35, 0.55], [0.5, 0.6], [0.65, 0.55]]) { await page.mouse.click(...at(fx, fy)); await page.waitForTimeout(250); }
console.log("points after 3 clicks:", await pointCount());
// Click anchor 2 (select as insert point), then add one more.
const anchor2 = page.locator(".mapboxgl-marker").filter({ hasText: /^2(Anchor |アンカー)2$/ });
console.log("anchor2 found:", await anchor2.count());
await anchor2.first().click(); await page.waitForTimeout(250);
console.log("points after clicking anchor (should stay 3):", await pointCount());
await shot("draw-selected", top);
await page.mouse.click(...at(0.5, 0.75)); await page.waitForTimeout(300);
console.log("points after insert:", await pointCount());
// Erase: click anchor 1.
await page.keyboard.press("e"); await page.waitForTimeout(150);
const anchor1 = page.locator(".mapboxgl-marker").filter({ hasText: /^1(Anchor |アンカー)1$/ });
await anchor1.first().click(); await page.waitForTimeout(300);
console.log("points after erase (should be 3):", await pointCount());
await page.getByTitle(/Show the list of points|点の一覧を表示/).click();
await page.waitForTimeout(250);
await shot("draw-points", { x: 360, y: 40, width: 1080, height: 560 });
await page.getByRole("button", { name: /^Done$|^完了$/ }).first().click(); await page.waitForTimeout(300);
console.log("draw bar gone:", (await page.locator('button[aria-haspopup="menu"]').filter({ hasText: "→" }).count()) === 0);

// Start drawing from the sidebar: leg 4 menu -> Draw.
await page.locator('aside button[aria-haspopup="menu"]').nth(3).click();
await page.getByRole("menuitemradio", { name: /Draw|手描き|描画/ }).click(); await page.waitForTimeout(1200);
console.log("draw bar leg:", await page.locator('main button[aria-haspopup="menu"]').first().innerText());
await shot("draw-from-sidebar");
await page.keyboard.press("Escape"); await page.waitForTimeout(200);

// Editor.
await page.getByText("三段壁展望台", { exact: true }).first().click(); await page.waitForTimeout(700);
await shot("editor");
await page.getByRole("tab", { name: /Photos|写真/ }).click(); await page.waitForTimeout(300);
await shot("editor-photos", { x: 360, y: 440, width: 1080, height: 420 });
await page.setViewportSize({ width: 1000, height: 680 }); await page.waitForTimeout(600);
await page.getByRole("tab", { name: /Narration|ナレーション/ }).click(); await page.waitForTimeout(300);
await shot("editor-1000");
await browser.close();
