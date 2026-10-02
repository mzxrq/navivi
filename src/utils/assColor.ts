import type { RGB } from "../components/ui/ColorSwatches";

// ASS writes colours as &HAABBGGRR: blue and red swapped against #RRGGBB, and alpha 00 = opaque, FF = invisible.
const ASS = /^&H([0-9a-f]{2})?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})&?$/i;

const parse = (ass: string | undefined) => ASS.exec((ass ?? "").trim());
const hex = (n: number) => Math.round(n).toString(16).padStart(2, "0").toUpperCase();

export function assToRgb(ass: string | undefined, fallback: RGB): RGB {
  const m = parse(ass);
  return m ? [parseInt(m[4], 16), parseInt(m[3], 16), parseInt(m[2], 16)] : fallback;
}

// A colour picked from the swatches keeps the alpha the value already had, so a translucent colour set by hand stays translucent.
export function rgbToAss([r, g, b]: RGB, previous?: string): string {
  const alpha = parse(previous)?.[1] ?? "00";
  return `&H${alpha.toUpperCase()}${hex(b)}${hex(g)}${hex(r)}`;
}

// 0 = invisible, 1 = solid. An ASS value without an alpha byte is solid.
export const assOpacity = (ass: string | undefined) => 1 - parseInt(parse(ass)?.[1] ?? "00", 16) / 255;

export function withOpacity(ass: string, opacity: number): string {
  const [r, g, b] = assToRgb(ass, [0, 0, 0]);
  return `&H${hex((1 - Math.min(1, Math.max(0, opacity))) * 255)}${hex(b)}${hex(g)}${hex(r)}`;
}

export function assToCss(ass: string | undefined, fallback: RGB): string {
  const [r, g, b] = assToRgb(ass, fallback);
  const opacity = 1 - parseInt(parse(ass)?.[1] ?? "00", 16) / 255;
  return `rgba(${r}, ${g}, ${b}, ${Math.round(opacity * 100) / 100})`;
}
