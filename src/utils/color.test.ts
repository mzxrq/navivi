import { describe, expect, it } from "vitest";
import { hexToHsv, hexToRgb, hsvToHex, normalizeHex, readableOn, rgbToHex } from "./color";

describe("normalizeHex", () => {
  it("accepts 3 and 6 digit hex with or without the hash, in any case", () => {
    expect(normalizeHex("#fff")).toBe("#FFFFFF");
    expect(normalizeHex("3b82f6")).toBe("#3B82F6");
    expect(normalizeHex("  #aBc ")).toBe("#AABBCC");
  });

  it("rejects anything else", () => {
    for (const bad of ["", "#12", "#12345", "#gggggg", "red", "#1234567"]) expect(normalizeHex(bad)).toBeNull();
  });
});

describe("rgb and hsv", () => {
  it("round-trips hex through rgb", () => {
    expect(hexToRgb("#3B82F6")).toEqual([59, 130, 246]);
    expect(rgbToHex(59, 130, 246)).toBe("#3B82F6");
    expect(rgbToHex(300, -5, 0.4)).toBe("#FF0000");
  });

  it("knows the primary colours in hsv", () => {
    expect(hexToHsv("#FF0000")).toEqual({ h: 0, s: 1, v: 1 });
    expect(hexToHsv("#00FF00").h).toBeCloseTo(120);
    expect(hexToHsv("#0000FF").h).toBeCloseTo(240);
    expect(hexToHsv("#FFFFFF")).toEqual({ h: 0, s: 0, v: 1 });
    expect(hexToHsv("#000000")).toEqual({ h: 0, s: 0, v: 0 });
  });

  it("converts hsv back to the same hex for a spread of colours", () => {
    for (const hex of ["#FF7E5F", "#8B5CF6", "#4287F5", "#123456", "#FEDCBA", "#808080"]) {
      expect(hsvToHex(hexToHsv(hex))).toBe(hex);
    }
    expect(hsvToHex({ h: 0, s: 0, v: 0.5 })).toBe("#808080");
    expect(hsvToHex({ h: 360, s: 1, v: 1 })).toBe("#FF0000");
  });
});

describe("readableOn", () => {
  it("picks black on light colours and white on dark ones", () => {
    expect(readableOn("#FFFFFF")).toBe("#000000");
    expect(readableOn("#FFD400")).toBe("#000000");
    expect(readableOn("#0B1020")).toBe("#FFFFFF");
    expect(readableOn("#4287F5")).toBe("#FFFFFF");
  });
});
