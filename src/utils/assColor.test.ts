import { describe, expect, it } from "vitest";
import { assOpacity, assToCss, assToRgb, rgbToAss, withOpacity } from "./assColor";

const WHITE: [number, number, number] = [255, 255, 255];

describe("assToRgb", () => {
  it("reads the defaults", () => {
    expect(assToRgb("&H00FFFFFF", [1, 2, 3])).toEqual([255, 255, 255]);
    expect(assToRgb("&H00000000", [1, 2, 3])).toEqual([0, 0, 0]);
  });

  it("swaps blue and red back (ASS is BGR)", () => {
    expect(assToRgb("&H0000FFFF", WHITE)).toEqual([255, 255, 0]); // yellow
    expect(assToRgb("&H000000FF", WHITE)).toEqual([255, 0, 0]); // red
    expect(assToRgb("&H00FF0000", WHITE)).toEqual([0, 0, 255]); // blue
  });

  it("accepts the shorter and trailing-ampersand spellings, in any case", () => {
    expect(assToRgb("&HFFFF00&", [0, 0, 0])).toEqual([0, 255, 255]);
    expect(assToRgb("&h00ffff00", [0, 0, 0])).toEqual([0, 255, 255]);
    expect(assToRgb("  &H00FFFFFF ", [0, 0, 0])).toEqual([255, 255, 255]);
  });

  it("falls back for anything it cannot read", () => {
    for (const bad of [undefined, "", "white", "#ffffff", "&HZZ", "&H0000FFFFFF"]) {
      expect(assToRgb(bad, [9, 8, 7])).toEqual([9, 8, 7]);
    }
  });
});

describe("rgbToAss", () => {
  it("writes BGR with an opaque alpha by default", () => {
    expect(rgbToAss([255, 255, 0])).toBe("&H0000FFFF");
    expect(rgbToAss([255, 0, 0])).toBe("&H000000FF");
    expect(rgbToAss([0, 0, 0])).toBe("&H00000000");
  });

  it("keeps the alpha of the value it replaces", () => {
    expect(rgbToAss([255, 0, 0], "&H80FFFFFF")).toBe("&H800000FF");
    expect(rgbToAss([255, 0, 0], "&Hff000000")).toBe("&HFF0000FF");
    expect(rgbToAss([255, 0, 0], "&HFFFFFF")).toBe("&H000000FF"); // 6 digits has no alpha to keep
    expect(rgbToAss([255, 0, 0], "junk")).toBe("&H000000FF");
  });

  it("round-trips every swatch-sized colour", () => {
    for (const rgb of [[59, 130, 246], [239, 68, 68], [16, 185, 129], [0, 0, 1], [1, 2, 3]] as [number, number, number][]) {
      expect(assToRgb(rgbToAss(rgb), WHITE)).toEqual(rgb);
    }
  });
});

describe("assToCss", () => {
  it("turns ASS alpha into opacity", () => {
    expect(assToCss("&H00FFFFFF", WHITE)).toBe("rgba(255, 255, 255, 1)");
    expect(assToCss("&HFF0000FF", WHITE)).toBe("rgba(255, 0, 0, 0)");
    expect(assToCss("&H800000FF", WHITE)).toBe("rgba(255, 0, 0, 0.5)");
  });

  it("uses the fallback, fully opaque, for an unreadable value", () => {
    expect(assToCss("nope", [0, 0, 0])).toBe("rgba(0, 0, 0, 1)");
  });
});

describe("opacity", () => {
  it("reads it from the alpha byte, 00 being solid", () => {
    expect(assOpacity("&H00000000")).toBe(1);
    expect(assOpacity("&H66000000")).toBeCloseTo(0.6, 2);
    expect(assOpacity("&HFF000000")).toBe(0);
    expect(assOpacity("&HFFFFFF")).toBe(1);
    expect(assOpacity(undefined)).toBe(1);
  });

  it("sets the alpha byte and keeps the colour", () => {
    expect(withOpacity("&H00112233", 0.6)).toBe("&H66112233");
    expect(withOpacity("&H66112233", 1)).toBe("&H00112233");
    expect(withOpacity("&H66112233", 0)).toBe("&HFF112233");
  });

  it("clamps what it is given", () => {
    expect(withOpacity("&H00000000", 2)).toBe("&H00000000");
    expect(withOpacity("&H00000000", -1)).toBe("&HFF000000");
  });

  it("round-trips every whole percent the slider can give", () => {
    for (let pct = 0; pct <= 100; pct++) {
      expect(Math.round(assOpacity(withOpacity("&H00000000", pct / 100)) * 100)).toBe(pct);
    }
  });
});
