import { describe, expect, it } from "vitest";
import { appendStop, legEnds, legIndexOf, mainLegCount, setEndsAtDestination, startSubCourse, subEnd, withSubLast } from "../../src/utils/courses";
import { stopLabel } from "../../src/utils/stopLabel";
import type { Waypoint } from "../../src/types";

const stop = (id: string, lat: number, patch: Partial<Waypoint> = {}): Waypoint => ({ id, lat, lng: 0, name: id.toUpperCase(), routeMode: "walking", ...patch });
const main = () => [stop("s", 0), stop("a", 1), stop("e", 2)];

describe("sub course", () => {
  it("branches from a main stop and has its own legs after the main ones", () => {
    let all = startSubCourse(main(), "a");
    all = appendStop(all, stop("x", 5), true);
    all = appendStop(all, stop("y", 6), true);
    const legs = legEnds(all).map(([f, t]) => `${f.name}>${t.name}`);
    expect(legs).toEqual(["S>A", "A>E", "A>X", "X>Y"]);
    expect(mainLegCount(all)).toBe(2);
    const anchor = all.find((w) => w.branchOf === "a")!;
    expect(legEnds(all)[2][0].lat).toBe(1); // the anchor sits on its main stop
    expect(legIndexOf(all, anchor.id)).toBe(2);
    expect(all.map((w) => stopLabel(all, all.indexOf(w)))).toEqual(["S", "1", "E", "1", "B1", "B2"]);
  });

  it("can end at the main destination, and new sub stops go before that end", () => {
    let all = appendStop(startSubCourse(main(), "a"), stop("x", 5), true);
    all = setEndsAtDestination(all, true);
    expect(subEnd(all)?.id).toBe("e");
    all = appendStop(all, stop("y", 6), true);
    expect(legEnds(all).slice(2).map(([f, t]) => `${f.name}>${t.name}`)).toEqual(["A>X", "X>Y", "Y>E"]);
    expect(subEnd(setEndsAtDestination(all, false))).toBeUndefined();
  });

  it("keeps main stops first: a new main stop joins the main course's end", () => {
    const all = appendStop(appendStop(startSubCourse(main(), "a"), stop("x", 5), true), stop("f", 3), false);
    expect(all.map((w) => w.id).slice(0, 4)).toEqual(["s", "a", "e", "f"]);
    const shuffled = [all[4], ...all.slice(0, 4), all[5]];
    expect(withSubLast(shuffled).map((w) => w.id)).toEqual(all.map((w) => w.id));
    expect(withSubLast(all)).toBe(all);
  });
});
