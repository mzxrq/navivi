import { describe, expect, it } from "vitest";
import type { Waypoint } from "../types";
import { collectCredits, creditLine, renameCredits, withFoundPhotos } from "./photoCredits";

const credit = (n: string) => ({ title: `File:${n}.jpg`, author: "Taro", license: "CC BY 4.0", url: `https://commons.wikimedia.org/wiki/File:${n}.jpg` });
const wp = (over: Partial<Waypoint> = {}): Waypoint => ({ id: "a", name: "A", lat: 0, lng: 0, routeMode: "walking", ...over });

describe("withFoundPhotos", () => {
  it("fills the empty slots after the user's own photos, with a still pan each and a credit", () => {
    const patch = withFoundPhotos(wp({ images: ["mine.jpg"], imagePans: ["panright"] }), [
      { path: "a.jpg", credit: credit("a") },
      { path: "b.jpg", credit: credit("b") },
      { path: "c.jpg", credit: credit("c") },
    ]);
    expect(patch?.images).toEqual(["mine.jpg", "a.jpg", "b.jpg"]);
    expect(patch?.imagePans).toEqual(["panright", "none", "none"]);
    expect(Object.keys(patch?.imageCredits ?? {})).toEqual(["a.jpg", "b.jpg"]);
  });

  it("changes nothing when the stop already has all its photos or the photo is already there", () => {
    expect(withFoundPhotos(wp({ images: ["1", "2", "3"] }), [{ path: "a.jpg", credit: credit("a") }])).toBeNull();
    expect(withFoundPhotos(wp({ images: ["a.jpg"] }), [{ path: "a.jpg", credit: credit("a") }])).toBeNull();
  });

  it("keeps the credits it already had", () => {
    const patch = withFoundPhotos(wp({ images: ["x.jpg"], imageCredits: { "x.jpg": credit("x") } }), [{ path: "y.jpg", credit: credit("y") }]);
    expect(Object.keys(patch?.imageCredits ?? {})).toEqual(["x.jpg", "y.jpg"]);
  });
});

describe("renameCredits", () => {
  it("moves each credit to its photo's new name, so saving and opening keep them attached", () => {
    const before = { "C:/Imports/Sandanbeki.jpg": credit("s"), "C:/Imports/Gone.jpg": credit("g") };
    const saved = renameCredits(before, new Map([["C:/Imports/Sandanbeki.jpg", "assets/image/Sandanbeki (2).jpg"]]));
    expect(saved).toEqual({ "assets/image/Sandanbeki (2).jpg": credit("s") }); // a photo that was removed takes its credit with it
    const reopened = renameCredits(saved, new Map([["assets/image/Sandanbeki (2).jpg", "C:/Proj/assets/image/Sandanbeki (2).jpg"]]));
    expect(reopened).toEqual({ "C:/Proj/assets/image/Sandanbeki (2).jpg": credit("s") });
  });

  it("gives nothing when no photo has a credit", () => {
    expect(renameCredits(undefined, new Map())).toBeUndefined();
    expect(renameCredits({ a: credit("a") }, new Map())).toBeUndefined();
  });
});

describe("collectCredits", () => {
  it("lists each photo still used once, leaving out skipped stops and stops that use the user's own videos", () => {
    const lines = collectCredits([
      wp({ images: ["a.jpg", "b.jpg"], imageCredits: { "a.jpg": credit("a"), "b.jpg": credit("a") } }),
      wp({ id: "b", images: ["c.jpg"], imageCredits: { "c.jpg": credit("c") }, skipAssetGeneration: true }),
      wp({ id: "c", images: ["d.jpg"], imageCredits: { "d.jpg": credit("d") }, videos: ["v.mp4"] }),
      wp({ id: "d", images: ["mine.jpg"] }),
    ]);
    expect(lines).toEqual([creditLine(credit("a"))]);
    expect(lines[0]).toBe("Taro · CC BY 4.0 · a.jpg");
  });
});
