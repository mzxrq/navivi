import type { RGB } from "../components/ui/ColorSwatches";

// ASS writes colours as &HAABBGGRR: blue and red swapped against #RRGGBB, and alpha 00 = opaque, FF = invisible.
const ASS = /^&H([0-9a-f]{2})?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})&?$/i;

const parse = (ass: string | undefined) => ASS.exec((ass ?? "").trim());

export function assToRgb(ass: string | undefined, fallback: RGB): RGB {
  const m = parse(ass);
  return m ? [parseInt(m[4], 16), parseInt(m[3], 16), parseInt(m[2], 16)] : fallback;
}

export function assToCss(ass: string | undefined, fallback: RGB): string {
  const [r, g, b] = assToRgb(ass, fallback);
  const opacity = 1 - parseInt(parse(ass)?.[1] ?? "00", 16) / 255;
  return `rgba(${r}, ${g}, ${b}, ${Math.round(opacity * 100) / 100})`;
}
