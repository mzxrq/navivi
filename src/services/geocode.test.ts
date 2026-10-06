import { describe, expect, it } from "vitest";
import { boundsAround, distanceKm, geocodeRoute, geocodeUrl, GeoPoint, Lookup, nameVariants, regionOf, stripRegion } from "./geocode";

const WAKAYAMA: GeoPoint = { lat: 34.0, lng: 135.19, country: "jp" };

describe("regionOf / stripRegion", () => {
  it("finds the area most names end with", () => {
    const places = ["Sainen-ji Temple, Wakayama", "Mt. Kabuto, Wakayama", "Kyoshi Sta., Osaka"];
    expect(regionOf(places)).toBe("Wakayama");
    expect(stripRegion(places[0], "Wakayama")).toBe("Sainen-ji Temple");
    expect(stripRegion(places[2], "Wakayama")).toBe("Kyoshi Sta., Osaka");
  });
  it("keeps the prefecture with the country instead of the country alone", () => {
    const places = ["Sainen-ji, Wakayama, Japan", "Mt. Kabuto, Wakayama, Japan", "Hongu, Wakayama, Japan"];
    expect(regionOf(places)).toBe("Wakayama, Japan");
    expect(stripRegion(places[0], "Wakayama, Japan")).toBe("Sainen-ji");
    expect(regionOf(["A, Tokyo, Japan", "B, Kyoto, Japan"])).toBe("Japan");
  });
  it("finds none when names carry no shared area", () => {    expect(regionOf(["Hongu", "Nachi"])).toBeNull();
    expect(regionOf(["A, X", "B, Y", "C, Z"])).toBeNull();
    expect(regionOf(["Only, Here"])).toBe("Here");
  });
});

describe("geocodeUrl limits", () => {
  const bounds = boundsAround(WAKAYAMA, 0.8);
  it("restricts Mapbox to a country and a box", () => {
    const url = geocodeUrl("Sainen-ji", { mapboxToken: "tk", country: "jp", bounds });
    expect(url).toContain("&country=jp");
    expect(url).toContain("&bbox=134.39,33.2,135.99,34.8");
  });
  it("makes the Nominatim box a hard limit", () => {
    const url = geocodeUrl("Sainen-ji", { country: "jp", bounds });
    expect(url).toContain("bounded=1");
    expect(url).toContain("countrycodes=jp");
  });
});

describe("distanceKm", () => {
  it("is about 111 km per degree of latitude", () => {
    expect(distanceKm({ lat: 34, lng: 135 }, { lat: 35, lng: 135 })).toBeCloseTo(111.2, 0);
  });
});

// A lookup that knows a few places and honors the box, like the real services do.
const world: Record<string, GeoPoint> = {
  Wakayama: WAKAYAMA,
  "Sainen-ji": { lat: 34.2547, lng: 135.1485 },
  "Mt. Kabuto": { lat: 34.27, lng: 135.2 },
};
const fakeLookup: Lookup = async (place, c) => {
  const hit = world[place];
  if (!hit) return null;
  if (c.bounds && (hit.lng < c.bounds.west || hit.lng > c.bounds.east || hit.lat < c.bounds.south || hit.lat > c.bounds.north)) return null;
  return hit;
};

describe("geocodeRoute", () => {
  it("resolves small places inside the region and puts an unknown one between its neighbors, marked uncertain", async () => {
    const places = ["Sainen-ji, Wakayama", "Nowhere, Wakayama", "Mt. Kabuto, Wakayama"];
    const out = await geocodeRoute(places, { lookup: fakeLookup });
    expect(out.failed).toEqual([]);
    expect(out.found.map((f) => [f.name, f.uncertain])).toEqual([
      ["Sainen-ji, Wakayama", false],
      ["Nowhere, Wakayama", true],
      ["Mt. Kabuto, Wakayama", false],
    ]);
    const middle = out.found[1].point;
    expect(middle.lat).toBeCloseTo((34.2547 + 34.27) / 2, 4);
    expect(middle.lng).toBeCloseTo((135.1485 + 135.2) / 2, 4);
  });

  it("fails every place when nothing could be located at all", async () => {
    const out = await geocodeRoute(["Nowhere, X", "Nothing, X"], { lookup: async () => null });
    expect(out.found).toEqual([]);
    expect(out.failed).toHaveLength(2);
  });

  it("keeps looking past its sample when the anchor sample all misses", async () => {
    const places = Array.from({ length: 20 }, (_, i) => `P${i}`);
    const lookup: Lookup = async (place) => (place === "P19" ? { lat: 35, lng: 135 } : null);
    const out = await geocodeRoute(places, { lookup });
    expect(out.failed).toEqual([]);
    expect(out.found[19].uncertain).toBe(false);
  });

  it("tries variants of a name and the local name from the rename step", async () => {
    const asked: string[] = [];
    const lookup: Lookup = async (place) => {
      asked.push(place);
      return place === "Wakayama" ? WAKAYAMA : place === "Nishinosho Station" || place === "猿坂峠" ? { lat: 34.25, lng: 135.11 } : null;
    };
    const out = await geocodeRoute(["Nishinosho Sta., Wakayama", "Sarusaka-toge Pass, Wakayama"], { lookup, rename: async () => ({ "Sarusaka-toge Pass": "猿坂峠" }) });
    expect(asked).toContain("Nishinosho Station");
    expect(out.found.map((f) => f.uncertain)).toEqual([false, false]);
  });

  it("does not accept the region's own point for a place that is not the region", async () => {
    const lookup: Lookup = async (place) => (place === "Wakayama" || place === "Shrine" ? WAKAYAMA : null);
    const out = await geocodeRoute(["Shrine, Wakayama", "Other, Wakayama"], { lookup });
    expect(out.found).toEqual([]);
    expect(out.failed).toHaveLength(2);
  });

  it("falls back to the median of where the names land when they carry no region", async () => {
    const seen: (Parameters<Lookup>[1])[] = [];
    const lookup: Lookup = async (place, c) => {
      seen.push(c);
      return fakeLookup(place, c);
    };
    const out = await geocodeRoute(["Sainen-ji", "Mt. Kabuto"], { lookup });
    expect(out.found).toHaveLength(2);
    expect(seen.some((c) => c.bounds)).toBe(true);
  });

  it("searches each stop only near the stop before it, so a far namesake is never taken", async () => {
    const boxes: number[] = [];
    const lookup: Lookup = async (place, c) => {
      if (place === "Wakayama") return WAKAYAMA;
      if (c.bounds) boxes.push(c.bounds.north - c.bounds.south);
      return place === "A" ? { lat: 34.05, lng: 135.19 } : place === "B" && c.bounds && c.bounds.north > 34.6 ? { lat: 34.6, lng: 135.19 } : null;
    };
    const out = await geocodeRoute(["A, Wakayama", "B, Wakayama"], { lookup, hopKm: 15 });
    expect(Math.min(...boxes)).toBeCloseTo((2 * 15) / 111, 2);
    expect(out.found[1].uncertain).toBe(true);
    expect(out.found[1].point.lat).toBeLessThan(34.1);
  });
});

describe("nameVariants", () => {
  it("expands abbreviations, drops notes and cuts generic suffixes", () => {
    expect(nameVariants("Nishinosho Sta.")).toContain("Nishinosho Station");
    expect(nameVariants("Sutra Mound #2 (Former Shinpuku-ji Temple)")).toContain("Sutra Mound");
    expect(nameVariants("Sarusaka-toge Pass")).toEqual(["Sarusaka-toge Pass", "Sarusaka"]);
    expect(nameVariants("Mt. Kabuto")).toContain("Mount Kabuto");
  });
});
