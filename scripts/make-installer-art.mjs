// Draws the installer's artwork from the app's own logo and writes the 24-bit BMPs NSIS wants:
//   src-tauri/installer/sidebar.bmp  164x314  (welcome and finish pages)
//   src-tauri/installer/header.bmp   150x57   (top right of the pages in between)
// Edit the HTML below and run `npm run art:installer`; the BMPs are committed so a build needs no browser.
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(root, "src-tauri", "installer");
const mark = readFileSync(join(root, "public", "navivi.svg"), "utf8");
const dataUri = (svg) => `data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}`;
const typeFile = dataUri(readFileSync(join(root, "public", "navivi-type.svg"), "utf8")); // a page made with setContent cannot load file:// URLs
const markUri = dataUri(mark);

const FONT = `'Segoe UI', 'Yu Gothic UI', sans-serif`; // single quotes: it sits inside style="..." attributes

const sidebar = `
<div style="position:relative;width:164px;height:314px;overflow:hidden;font-family:${FONT};
  background:linear-gradient(172deg,#0a0f1f 0%,#111d3b 52%,#1b3d8c 100%);">
  <svg width="164" height="314" style="position:absolute;inset:0" viewBox="0 0 164 314">
    <defs>
      <linearGradient id="r" x1="0" y1="1" x2="1" y2="0">
        <stop offset="0" stop-color="#3b82f6"/><stop offset=".5" stop-color="#8b5cf6"/><stop offset="1" stop-color="#ff7e5f"/>
      </linearGradient>
    </defs>
    <path d="M-10 300 C 40 292, 52 236, 92 232 S 150 214, 176 168" fill="none" stroke="url(#r)" stroke-width="3"
      stroke-linecap="round" stroke-dasharray="1 9" opacity=".85"/>
    <path d="M-10 262 C 30 258, 60 210, 100 214 S 150 190, 176 130" fill="none" stroke="#ffffff" stroke-opacity=".07" stroke-width="1.2"/>
    <path d="M-10 282 C 34 276, 56 224, 96 224 S 150 200, 176 150" fill="none" stroke="#ffffff" stroke-opacity=".07" stroke-width="1.2"/>
    <circle cx="92" cy="232" r="4.5" fill="#fff"/><circle cx="92" cy="232" r="9" fill="none" stroke="#fff" stroke-opacity=".35"/>
  </svg>
  <img src="${markUri}" width="64" height="64" style="position:absolute;left:20px;top:26px"/>
  <img src="${typeFile}" height="25" style="position:absolute;left:20px;top:108px;filter:brightness(0) invert(1)"/>
  <div style="position:absolute;left:20px;top:146px;width:130px;color:#a9bde8;font-size:11.5px;line-height:1.45">
    Turn your routes into narrated travel videos.</div>
</div>`;

const header = `
<div style="position:relative;width:150px;height:57px;background:#0f172a;font-family:${FONT}">
  <img src="${markUri}" width="40" height="40" style="position:absolute;right:14px;top:8px"/>
</div>`;

async function render(browser, html, width, height) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  await page.setContent(`<html><body style="margin:0">${html}</body></html>`);
  await page.waitForFunction(() => [...document.images].every((img) => img.complete));
  await page.waitForTimeout(200);
  const png = await page.screenshot({ type: "png", clip: { x: 0, y: 0, width, height } });
  await page.close();
  return { png };
}

// Decodes the PNG in the browser and returns its RGBA pixels, then writes them as a bottom-up 24-bit BMP.
async function toBmp(browser, png, width, height, file) {
  const page = await browser.newPage();
  const rgba = await page.evaluate(
    async ([b64, w, h]) => {
      const img = new Image();
      img.src = `data:image/png;base64,${b64}`;
      await img.decode();
      const canvas = document.createElement("canvas");
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(img, 0, 0);
      return Array.from(ctx.getImageData(0, 0, w, h).data);
    },
    [png.toString("base64"), width, height],
  );
  await page.close();

  const rowSize = Math.ceil((width * 3) / 4) * 4;
  const body = Buffer.alloc(rowSize * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const src = ((height - 1 - y) * width + x) * 4; // BMP rows run bottom to top
      const dst = y * rowSize + x * 3;
      body[dst] = rgba[src + 2];
      body[dst + 1] = rgba[src + 1];
      body[dst + 2] = rgba[src];
    }
  }
  const head = Buffer.alloc(54);
  head.write("BM", 0);
  head.writeUInt32LE(54 + body.length, 2);
  head.writeUInt32LE(54, 10);
  head.writeUInt32LE(40, 14);
  head.writeInt32LE(width, 18);
  head.writeInt32LE(height, 22);
  head.writeUInt16LE(1, 26);
  head.writeUInt16LE(24, 28);
  head.writeUInt32LE(body.length, 34);
  head.writeInt32LE(2835, 38);
  head.writeInt32LE(2835, 42);
  writeFileSync(file, Buffer.concat([head, body]));
}

mkdirSync(out, { recursive: true });
const browser = await chromium.launch();
for (const [name, html, w, h] of [["sidebar", sidebar, 164, 314], ["header", header, 150, 57]]) {
  const { png } = await render(browser, html, w, h);
  writeFileSync(join(out, `${name}.png`), png); // kept beside the BMP for a quick look
  await toBmp(browser, png, w, h, join(out, `${name}.bmp`));
  console.log(`${name}.bmp ${w}x${h}`);
}
await browser.close();
