import { describe, expect, it } from "vitest";
import { stopLabel } from "./stopLabel";
import type { Waypoint } from "../types";

const wp = (isStopBy = false) => ({ id: Math.random().toString(), lat: 0, lng: 0, name: "", isStopBy }) as Waypoint;

describe("stopLabel", () => {
  it("numbers stop-bys on their own, not by position", () => {
    const list = [wp(), wp(true), wp(), wp(), wp(true), wp(true), wp()];
    expect(list.map((_, i) => stopLabel(list, i))).toEqual(["S", "+1", "1", "2", "+2", "+3", "E"]);
  });
});
