// Context menus (map pin, leg, via point, text field, map), toasts and the
// project manager. Usage (from repo root): node menus.mjs <outDir> [theme] [locale]
import { chromium } from "@playwright/test";
const [out, theme = "light", locale = "en"] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
page.on("pageerror", (e) => console.log("pageerror", e.message));
const base = `http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html?theme=${theme}&locale=${locale}`;
const s = (n, clip) => page.screenshot({ path: `${out}/${theme}-${locale}-${n}.png`, ...(clip ? { clip } : {}) });
const menuCount = () => page.locator("[data-context-menu]").count();

await page.goto(`${base}&stops=demo&render=0`);
await page.waitForTimeout(3000);

// Map pin -> stop menu, then hover "Route to next stop" submenu.
const pins = page.locator(".mapboxgl-marker").filter({ has: page.locator("svg text") });
await pins.nth(1).locator("svg").click({ button: "right", force: true });
await page.waitForTimeout(250);
console.log("pin menu open:", await menuCount());
await page.getByRole("menuitem", { name: /Route to next stop|次の地点までの移動/ }).hover();
await page.waitForTimeout(400);
await s("pin-menu");
await page.keyboard.press("Escape"); await page.keyboard.press("Escape");
await page.waitForTimeout(150);
console.log("after Escape x2:", await menuCount());

// Keyboard: open again, ArrowDown x2, ArrowRight into a submenu.
await pins.nth(1).locator("svg").click({ button: "right", force: true });
await page.waitForTimeout(200);
for (let i = 0; i < 3; i++) await page.keyboard.press("ArrowDown");
await page.keyboard.press("ArrowRight");
await page.waitForTimeout(250);
console.log("panels after ArrowRight:", await menuCount(), "focused:", await page.evaluate(() => document.activeElement?.textContent));
await page.mouse.click(700, 700);

// Via point: right-click opens a menu and does NOT delete.
const viaBefore = await page.locator(".mapboxgl-marker .bg-violet-500").count();
await page.locator(".mapboxgl-marker .bg-violet-500").first().click({ button: "right", force: true });
await page.waitForTimeout(250);
console.log("via before:", viaBefore, "after right-click:", await page.locator(".mapboxgl-marker .bg-violet-500").count(), "menu:", await menuCount());
await s("via-menu");
await page.getByRole("menuitem", { name: /^Remove via point$|^中継点を削除$/ }).click();
await page.waitForTimeout(250);
console.log("via after Remove:", await page.locator(".mapboxgl-marker .bg-violet-500").count());

// Sidebar leg row.
await page.locator("aside button[aria-haspopup='menu']").first().click({ button: "right", force: true });
await page.waitForTimeout(250);
await s("leg-menu");
await page.keyboard.press("Escape");

// Text field.
const search = page.locator("aside input").first();
await search.fill("Shirahama beach");
await search.selectText();
await search.click({ button: "right", force: true });
await page.waitForTimeout(250);
await s("text-menu", { x: 0, y: 40, width: 500, height: 300 });
await page.keyboard.press("Escape");

// Empty map.
await page.mouse.click(1100, 650, { button: "right" });
await page.waitForTimeout(250);
await s("map-menu");
await page.keyboard.press("Escape");

// Toasts.
await page.evaluate(() => {
  window.__toast("Project saved to shirahama.nvv", "success");
  window.__toast("Failed to read project file: the archive is damaged or was written by a newer version.", "error");
  window.__toast("Quick Render started for SHIRAHAMA", "info");
});
await page.waitForTimeout(500);
await s("toasts", { x: 780, y: 480, width: 500, height: 320 });

// Project manager.
await page.goto(`${base}&view=title&render=0`);
await page.waitForTimeout(1500);
await s("title");
await page.getByTitle(/More actions|その他の操作/).first().click({ force: true });
await page.waitForTimeout(250);
await s("title-menu");
await page.getByRole("menuitem", { name: /^Rename$|名前を変更/ }).click();
await page.waitForTimeout(250);
await s("title-rename");
await page.keyboard.press("Escape");
await page.getByRole("button", { name: /Table View|テーブル/ }).click();
await page.waitForTimeout(250);
await s("title-list");
await browser.close();
