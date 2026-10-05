import { describe, expect, it } from "vitest";
import { splitThoughts } from "./thoughts";

describe("splitThoughts", () => {
  it("leaves plain text alone", () => {
    expect(splitThoughts("こんにちは")).toEqual({ text: "こんにちは", thoughts: "" });
  });

  it("removes a finished think block and returns it as thoughts", () => {
    expect(splitThoughts("<think>plan it</think>本文")).toEqual({ text: "本文", thoughts: "plan it" });
  });

  it("hides a block that is still being written", () => {
    expect(splitThoughts("<think>still going")).toEqual({ text: "", thoughts: "still going" });
  });

  it("handles the other markers", () => {
    expect(splitThoughts("<thought>a</thought>b").text).toBe("b");
    expect(splitThoughts("<|channel>thought x<channel|>y").text).toBe("y");
  });
});
