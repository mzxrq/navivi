// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { resolveVideoStyle } from "./constants";

const editorPicks = (id: string) => localStorage.setItem("map-style", id);
afterEach(() => localStorage.clear());

describe("resolveVideoStyle", () => {
  it("follows the editor's map by default", () => {
    editorPicks("dark");
    expect(resolveVideoStyle({})).toEqual({ follow: true, id: "mapbox/dark-v11" });
    editorPicks("satellite");
    expect(resolveVideoStyle({})).toEqual({ follow: true, id: "mapbox/satellite-streets-v12" });
  });

  it("keeps a style that was chosen by hand, and a project from before this setting", () => {
    editorPicks("dark");
    expect(resolveVideoStyle({ follow_editor_map_style: false, mapbox_style_id: "mapbox/streets-v12" })).toEqual({ follow: false, id: "mapbox/streets-v12" });
    expect(resolveVideoStyle({ mapbox_style_id: "mapbox/streets-v12" })).toEqual({ follow: false, id: "mapbox/streets-v12" });
    expect(resolveVideoStyle({ follow_editor_map_style: false })).toEqual({ follow: false, id: undefined });
  });

  it("uses the default look when the editor's map is not a Mapbox style the video can draw", () => {
    editorPicks("osm");
    expect(resolveVideoStyle({})).toEqual({ follow: true, id: undefined });
    editorPicks("standard");
    expect(resolveVideoStyle({ follow_editor_map_style: true })).toEqual({ follow: true, id: undefined });
  });
});
