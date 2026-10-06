import { chromium } from "@playwright/test";
const out = process.argv[2];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.on("pageerror", (e) => console.log("pageerror", e.message));
await page.goto("http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html?theme=light&locale=en&stops=demo&render=0");
await page.waitForTimeout(3000);
// Click the 3rd pin on the map.
const pins = page.locator(".mapboxgl-marker").filter({ has: page.locator("svg text") });
console.log("pins:", await pins.count());
await pins.nth(2).locator("svg").click();
await page.waitForTimeout(600);
const activeRow = await page.evaluate(() => {
  const el = [...document.querySelectorAll("aside div")].find((d) => d.className.includes("bg-navi/8"));
  return el ? el.textContent.trim().slice(0, 40) : null;
});
console.log("active sidebar row:", activeRow);
await page.screenshot({ path: `${out}/pin-select.png` });
// Rotate across south and read the needle transform.
const needle = page.locator('button[aria-label*="North"] svg');
const angles = [];
await page.locator(".mapboxgl-canvas").focus();
for (let i = 0; i < 16; i++) {
  await page.keyboard.press("Shift+ArrowLeft");
  await page.waitForTimeout(350);
  angles.push(await needle.evaluate((el) => el.style.transform.replace(/rotate\((.*)deg\)/, "$1")));
}
console.log("needle:", angles.join(" | "));
await browser.close();
