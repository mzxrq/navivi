// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { libassEmScale, textStyleToCss } from "../../src/utils/textStyle";
import { DEFAULT_TEXT_TITLE_STYLE } from "../../src/utils/textStyle";

const fakeCanvas = (ascent: number, descent: number) =>
  vi.spyOn(document, "createElement").mockImplementation(((tag: string) =>
    tag === "canvas"
      ? { getContext: () => ({ font: "", measureText: () => ({ fontBoundingBoxAscent: ascent, fontBoundingBoxDescent: descent }) }) }
      : document.createElementNS("http://www.w3.org/1999/xhtml", tag)) as typeof document.createElement);

afterEach(() => vi.restoreAllMocks());

describe("libassEmScale", () => {
  it("is em over line height: a font with a 139 px line at 100 px renders at 72%", () => {
    fakeCanvas(110, 29);
    expect(libassEmScale("Scale Test A", true)).toBeCloseTo(100 / 139, 3);
  });

  it("keeps the CSS size when there is no canvas to measure with", () => {
    expect(libassEmScale("Scale Test B", false)).toBe(1);
  });

  it("scales the preview's font size, so it matches the export's smaller glyphs", () => {
    fakeCanvas(110, 29);
    const style = { ...DEFAULT_TEXT_TITLE_STYLE, font_family: "Scale Test C", font_size: 108 };
    // 108 px of a 1080 frame is 10cqh in CSS; libass draws it at 72% of that
    expect(parseFloat(String(textStyleToCss(style).fontSize))).toBeCloseTo(10 * (100 / 139), 2);
  });
});

import { applyLineMargins } from "../../src/utils/textStyle";

describe("applyLineMargins", () => {
  const ys = { kickerY: 100, titleY: 160, subY: 240 };
  const all = { kicker: true, title: true, subtitle: true };

  it("changes nothing without margins", () => {
    expect(applyLineMargins("top", ys, {}, all)).toEqual(ys);
    expect(applyLineMargins("middle", ys, { title: 0 }, all)).toEqual(ys);
  });

  it("pushes a line and everything under it down, keeping the first line of a top block in place", () => {
    expect(applyLineMargins("top", ys, { title: 20 }, all)).toEqual({ kickerY: 100, titleY: 180, subY: 260 });
    expect(applyLineMargins("top", ys, { kicker: 10 }, all)).toEqual({ kickerY: 110, titleY: 170, subY: 250 });
  });

  it("keeps the last line of a bottom block and centres a middle block", () => {
    expect(applyLineMargins("bottom", ys, { subtitle: 30 }, all)).toEqual({ kickerY: 70, titleY: 130, subY: 240 });
    expect(applyLineMargins("middle", ys, { subtitle: 30 }, all)).toEqual({ kickerY: 85, titleY: 145, subY: 255 });
  });

  it("ignores the margin of a line that is not shown and accepts negative ones", () => {
    expect(applyLineMargins("top", ys, { kicker: 50, subtitle: -10 }, { kicker: false, title: true, subtitle: true })).toEqual({ kickerY: 100, titleY: 160, subY: 230 });
  });
});
