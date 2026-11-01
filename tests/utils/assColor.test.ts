import { describe, expect, it } from "vitest";
import { assToCss, assToRgb } from "../../src/utils/assColor";

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

