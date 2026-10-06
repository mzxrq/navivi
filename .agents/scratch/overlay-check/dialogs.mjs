// NewProject, SaveAs, UnsavedChanges, ErrorBoundary, ScriptInput.
// Usage (from repo root): node dialogs.mjs <outDir> [theme] [locale]
import { chromium } from "@playwright/test";
const [out, theme = "light", locale = "en"] = process.argv.slice(2);
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
page.on("pageerror", (e) => console.log("pageerror", e.message.slice(0, 80)));
const base = `http://127.0.0.1:1420/.agents/scratch/overlay-check/index.html?theme=${theme}&locale=${locale}&render=0`;
const s = (n, clip) => page.screenshot({ path: `${out}/${theme}-${locale}-${n}.png`, ...(clip ? { clip } : {}) });

await page.goto(`${base}&view=new`);
await page.waitForTimeout(1500);
await s("new-project");

await page.goto(`${base}&stops=demo`);
await page.waitForTimeout(2500);
await page.getByRole("button", { name: /^(Menu|メニュー)$/ }).click();
await page.getByRole("menuitem", { name: /Save As|名前を付けて/ }).click();
await page.waitForTimeout(700);
await s("save-as");
await page.keyboard.press("Escape");
await page.getByRole("button", { name: /^(Menu|メニュー)$/ }).click();
await page.getByRole("menuitem").filter({ hasText: /Project Manager|プロジェクトマネージャー|プロジェクト管理/ }).click();
await page.waitForTimeout(400);
await s("unsaved");
await page.keyboard.press("Escape");

// ScriptInput: type, blur, check it saved.
await page.getByText("白良浜", { exact: true }).first().click();
await page.waitForTimeout(600);
const ta = page.locator("textarea").first();
await ta.click(); await ta.fill("白良浜は白い砂浜で有名です。");
await page.waitForTimeout(200);
await s("script-dirty", { x: 360, y: 420, width: 920, height: 380 });
await page.locator("header, main").first().click({ position: { x: 5, y: 5 } }).catch(() => {});
await page.getByRole("tab").first().focus();
await page.waitForTimeout(300);
console.log("save button after blur:", await page.getByRole("button", { name: /^(Saved|保存済み)$/ }).count() > 0 ? "Saved" : "not saved");

await page.goto(`${base}&stops=demo&crash=1`);
await page.waitForTimeout(1500);
await s("crash");
await page.getByRole("button", { name: /Show details|詳細を表示/ }).click();
await page.waitForTimeout(200);
await s("crash-details");
await browser.close();
