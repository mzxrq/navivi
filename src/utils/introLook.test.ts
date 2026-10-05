import { describe, expect, it } from "vitest";
import { INTRO_DEFAULTS, introLookOf, introSizeToCqw } from "./introLook";

describe("introLookOf", () => {
  it("falls back to the defaults when nothing is set", () => {
    expect(introLookOf(undefined)).toEqual(INTRO_DEFAULTS);
  });

  it("overrides only the fields that are set", () => {
    const look = introLookOf({ subtitle_size: 120, title_bold: false });
    expect(look.subtitle_size).toBe(120);
    expect(look.title_bold).toBe(false);
    expect(look.title_size).toBe(INTRO_DEFAULTS.title_size);
  });
});

describe("introSizeToCqw", () => {
  it("expresses a size as a share of the 1920px frame", () => {
    expect(introSizeToCqw(192)).toBe("10.000cqw");
  });
});
