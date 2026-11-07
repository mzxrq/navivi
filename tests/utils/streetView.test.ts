import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/path", () => ({ basename: vi.fn(), dirname: vi.fn() }));
vi.mock("@tauri-apps/plugin-fs", () => ({ exists: vi.fn() }));

import { stopLabel } from "../../src/utils/stopLabel";
import { photoFileNames } from "../../src/utils/fileNames";
import type { Waypoint } from "../../src/types";

const wp = (id: string, patch: Partial<Waypoint> = {}): Waypoint => ({ id, name: id, lat: 0, lng: 0, routeMode: "walking", ...patch });
const view = (id: string) => wp(id, { isStopBy: true, connectToRoute: false, isStreetView: true, images: [`C:/in/${id}.jpg`] });

describe("street view waypoints", () => {
  it("count V1, V2 and leave the stop and stop-by numbers alone", () => {
    const list = [wp("s"), view("corner"), wp("a"), wp("b", { isStopBy: true }), view("bridge"), wp("e")];
    expect(list.map((_, i) => stopLabel(list, i))).toEqual(["S", "V1", "1", "+1", "V2", "E"]);
  });

  it("name their photos place-v1-1", () => {
    expect([...photoFileNames([wp("s"), view("corner"), wp("e")]).values()]).toEqual(["corner-v1-1.jpg"]);
  });
});
