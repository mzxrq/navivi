import { t } from "@lingui/core/macro";

export type RGB = [number, number, number];

export const PRESET_COLORS = [
  "#3b82f6",
  "#ef4444",
  "#10b981",
  "#f59e0b",
  "#8b5cf6",
  "#ec4899",
  "#ffffff",
  "#000000",
];

export function presetColorNames(): string[] {
  return [t`Blue`, t`Red`, t`Green`, t`Orange`, t`Purple`, t`Pink`, t`White`, t`Black`];
}

export const rgbToHex = (rgb: RGB) =>
  "#" + rgb.map((x) => Math.round(x).toString(16).padStart(2, "0")).join("");

export const hexToRgb = (hex: string): RGB => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
];

export function ColorSwatches({
  color,
  onChange,
}: {
  color: RGB | null;
  onChange: (c: RGB) => void;
}) {
  const names = presetColorNames();
  const currentHex = color ? rgbToHex(color) : null;
  const isCustom = currentHex !== null && !PRESET_COLORS.includes(currentHex);
  return (
    <div className="flex items-center gap-1.5">
      {PRESET_COLORS.map((c, i) => (
        <button
          key={c}
          type="button"
          onClick={() => onChange(hexToRgb(c))}
          aria-label={names[i]}
          aria-pressed={currentHex === c}
          title={names[i]}
          className={`w-5 h-5 rounded-full ring-1 ring-inset ring-black/10 dark:ring-white/15 transition-transform hover:scale-110 ${
            currentHex === c ? "outline-2 outline-offset-2 outline-navi" : ""
          }`}
          style={{ backgroundColor: c }}
        />
      ))}
      <label
        title={t`Custom Color`}
        className={`relative w-5 h-5 rounded-full cursor-pointer overflow-hidden ring-1 ring-inset ring-black/10 dark:ring-white/15 bg-[conic-gradient(#ef4444,#f59e0b,#10b981,#3b82f6,#8b5cf6,#ef4444)] transition-transform hover:scale-110 ${
          isCustom ? "outline-2 outline-offset-2 outline-navi" : ""
        }`}
      >
        <input
          type="color"
          value={currentHex ?? "#3b82f6"}
          onChange={(e) => onChange(hexToRgb(e.target.value))}
          className="absolute inset-0 opacity-0 cursor-pointer"
        />
      </label>
    </div>
  );
}
