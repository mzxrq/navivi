import { describe, expect, it } from "vitest";
import { estimateSeconds, nextStopNumber, spokenChars } from "../../src/utils/overviewScript";

describe("overview script length", () => {
  it("does not count cue tags as spoken", () => {
    expect(spokenChars("{start}あいう{1}えお{go}{end}")).toBe(5);
    expect(spokenChars("{unknown}")).toBe(9);
  });

  it("estimates seconds from the voice speed", () => {
    expect(estimateSeconds("あ".repeat(100), 5)).toBe(20);
    expect(estimateSeconds("あ", 0)).toBe(0);
  });

  it("numbers the next stop cue after the highest one", () => {
    expect(nextStopNumber("")).toBe(1);
    expect(nextStopNumber("{1}あ{3}い{go}")).toBe(4);
  });
});
