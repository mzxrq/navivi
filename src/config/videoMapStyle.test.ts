// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { editorStyleForVideo, mapStyles, videoMapStyles } from "./constants";

describe("the editor's map style as a video style", () => {
  beforeEach(() => localStorage.clear());

  it("follows the saved editor style when it is a Mapbox style the video can draw", () => {
    expect(editorStyleForVideo()).toBe("mapbox/outdoors-v12");
    localStorage.setItem("map-style", "dark");
    expect(editorStyleForVideo()).toBe("mapbox/dark-v11");
    localStorage.setItem("map-style", "light");
    expect(editorStyleForVideo()).toBe("mapbox/streets-v12");
  });

  it("is null for styles the video cannot use", () => {
    for (const id of ["standard", "osm", "gsi-japan"]) {
      localStorage.setItem("map-style", id);
      expect(editorStyleForVideo()).toBeNull();
    }
  });

  it("offers only owner/id styles", () => {
    expect(videoMapStyles.every((s) => /^[\w-]+\/[\w-]+$/.test(s.id))).toBe(true);
    expect(mapStyles.length).toBeGreaterThan(0);
  });
});
