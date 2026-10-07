import { describe, expect, it } from "vitest";
import { estimateSeconds, lengthVerdict, nextStopNumber, spokenChars } from "./overviewScript";

const limits = { chars_per_second: 5, target_seconds: 90, min_seconds: 60, max_seconds: 120 };

describe("overview script length", () => {
  it("does not count cue tags as spoken", () => {
    expect(spokenChars("{start}あいう{1}えお{go}{end}")).toBe(5);
    expect(spokenChars("{unknown}")).toBe(9);
  });

  it("estimates seconds from the voice speed", () => {
    expect(estimateSeconds("あ".repeat(100), 5)).toBe(20);
    expect(estimateSeconds("あ", 0)).toBe(0);
  });

  it("judges against 60-120 s with 3 s of slack", () => {
    expect(lengthVerdict(0, limits)).toBe("empty");
    expect(lengthVerdict(56, limits)).toBe("short");
    expect(lengthVerdict(57, limits)).toBe("ok");
    expect(lengthVerdict(123, limits)).toBe("ok");
    expect(lengthVerdict(124, limits)).toBe("long");
  });

  it("numbers the next stop cue after the highest one", () => {
    expect(nextStopNumber("")).toBe(1);
    expect(nextStopNumber("{1}あ{3}い{go}")).toBe(4);
  });
});
