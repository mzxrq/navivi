export interface Hsv {
  h: number; // 0-360
  s: number; // 0-1
  v: number; // 0-1
}

/** "#abc", "abc", "#AABBCC" or "aabbcc" as "#AABBCC"; null when it is not a colour. */
export function normalizeHex(input: string): string | null {
  const text = input.trim().replace(/^#/, "");
  if (/^[0-9a-f]{3}$/i.test(text)) return `#${[...text].map((c) => c + c).join("")}`.toUpperCase();
  if (/^[0-9a-f]{6}$/i.test(text)) return `#${text}`.toUpperCase();
  return null;
}

export function hexToRgb(hex: string): [number, number, number] {
  const n = normalizeHex(hex) ?? "#000000";
  return [parseInt(n.slice(1, 3), 16), parseInt(n.slice(3, 5), 16), parseInt(n.slice(5, 7), 16)];
}

const byte = (n: number) => Math.round(Math.min(255, Math.max(0, n))).toString(16).padStart(2, "0");

export const rgbToHex = (r: number, g: number, b: number) => `#${byte(r)}${byte(g)}${byte(b)}`.toUpperCase();

export function hexToHsv(hex: string): Hsv {
  const [r, g, b] = hexToRgb(hex).map((c) => c / 255);
  const max = Math.max(r, g, b);
  const delta = max - Math.min(r, g, b);
  let h = 0;
  if (delta > 0) {
    if (max === r) h = ((g - b) / delta) % 6;
    else if (max === g) h = (b - r) / delta + 2;
    else h = (r - g) / delta + 4;
    h = (h * 60 + 360) % 360;
  }
  return { h, s: max === 0 ? 0 : delta / max, v: max };
}

export function hsvToHex({ h, s, v }: Hsv): string {
  const f = (n: number) => {
    const k = (n + h / 60) % 6;
    return v - v * s * Math.max(0, Math.min(k, 4 - k, 1));
  };
  return rgbToHex(f(5) * 255, f(3) * 255, f(1) * 255);
}

/** Black or white, whichever reads better on `hex`. */
export function readableOn(hex: string): "#000000" | "#FFFFFF" {
  const [r, g, b] = hexToRgb(hex);
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#000000" : "#FFFFFF";
}
