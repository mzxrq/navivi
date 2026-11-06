import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@tauri-apps/api/path", () => ({ basename: vi.fn(), dirname: vi.fn() }));
vi.mock("@tauri-apps/plugin-fs", () => ({ exists: vi.fn() }));

import { photoFileNames } from "../../src/utils/fileNames";
import type { Waypoint } from "../../src/types";

const stop = (name: string, images: string[], patch: Partial<Waypoint> = {}): Waypoint => ({ id: name, name, lat: 0, lng: 0, routeMode: "walking", images, ...patch });

describe("photo file names", () => {
  it("names photos place-stop-photo, stop-bys s1 and closed places c1", () => {
    const names = photoFileNames([
      stop("Station", ["C:/in/a.jpg"]),
      stop("葛木水分神社", ["C:/in/b.png", "C:/in/c.JPG"]),
      stop("Mound", ["C:/in/d.jpg"], { isStopBy: true }),
      stop("Old: hall?", ["C:/in/e.jpg"], { isStopBy: true, inaccessible: true }),
      stop("Port", ["C:/in/f.webp"]),
    ]);
    expect([...names.values()]).toEqual([
      "Station-S-1.jpg", "葛木水分神社-1-1.png", "葛木水分神社-1-2.JPG", "Mound-s1-1.jpg", "Old hall-c1-1.jpg", "Port-E-1.webp",
    ]);
  });
});