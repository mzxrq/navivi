import { describe, expect, it, vi } from "vitest";
import { boundsAround, distanceKm, geocodePlace, geocodeRoute, geocodeUrl, GeoPoint, Lookup, nameVariants, regionOf, spikes, stripRegion } from "./geocode";

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
  it("asks Nominatim for a few matches when it knows where the route is, so the closest can be chosen", () => {
    expect(geocodeUrl("甲山", { near: WAKAYAMA })).toContain("limit=5");
    expect(geocodeUrl("甲山", {})).toContain("limit=1");
  });
  it("makes the Nominatim box a hard limit", () => {
    const url = geocodeUrl("Sainen-ji", { country: "jp", bounds });
    expect(url).toContain("bounded=1");
    expect(url).toContain("countrycodes=jp");
  });
});

describe("geocodePlace", () => {
  it("takes the namesake closest to the route, not the first one OpenStreetMap lists", async () => {
    const hits = [
      { lat: "35.6964", lon: "138.6286" },
      { lat: "34.2322", lon: "135.1916" },
    ];
    vi.stubGlobal("fetch", async () => ({ json: async () => hits }));
    try {
      const point = await geocodePlace("甲山", { near: WAKAYAMA });
      expect(point).toMatchObject({ lat: 34.2322, lng: 135.1916 });
    } finally {
      vi.unstubAllGlobals();
    }
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

  it("in Japan asks for local names up front, tries them first, and keeps both names for display", async () => {
    const asked: string[] = [];
    const lookup: Lookup = async (place) => {
      asked.push(place);
      return place === "Wakayama" ? WAKAYAMA : place === "西念寺" ? { lat: 34.2547, lng: 135.1485 } : null;
    };
    let renameCalls = 0;
    const rename = async (names: string[]) => {
      renameCalls += 1;
      expect(names).toEqual(["Sainen-ji Temple"]);
      return { "Sainen-ji Temple": "西念寺" };
    };
    const out = await geocodeRoute(["Sainen-ji Temple, Wakayama"], { lookup, rename });
    expect(renameCalls).toBe(1);
    expect(asked.indexOf("西念寺")).toBeLessThan(asked.indexOf("Sainen-ji Temple") === -1 ? Infinity : asked.indexOf("Sainen-ji Temple"));
    expect(out.found[0]).toMatchObject({ name: "Sainen-ji Temple, Wakayama", shortName: "Sainen-ji Temple", localName: "西念寺", uncertain: false });
  });

  it("does not ask for local names up front outside Japan", async () => {
    const rename = async () => {
      throw new Error("not needed");
    };
    const lookup: Lookup = async (place) => (place === "Paris" ? { lat: 48.85, lng: 2.35, country: "fr" } : place === "Louvre" ? { lat: 48.86, lng: 2.34, country: "fr" } : null);
    const out = await geocodeRoute(["Louvre, Paris"], { lookup, rename });
    expect(out.found[0].uncertain).toBe(false);
    expect(out.found[0].localName).toBeUndefined();
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

describe("spikes", () => {
  const p = (lat: number, lng: number): GeoPoint => ({ lat, lng });
  it("finds a stop far off the line between the stops around it", () => {
    expect(spikes([p(34.25, 135.11), p(34.53, 134.99), p(34.27, 135.12), p(34.29, 135.15)])).toEqual([1]);
  });
  it("leaves an ordinary route, a short detour and missing stops alone", () => {
    expect(spikes([p(34.25, 135.11), null, p(34.27, 135.12), p(34.29, 135.15)])).toEqual([]);
    expect(spikes([p(34.0, 135.0), p(34.05, 135.05), p(34.1, 135.1)])).toEqual([]);
    expect(spikes([p(34.0, 135.0), p(34.04, 135.0), p(34.0, 135.01)])).toEqual([]);
  });
});

describe("geocodeRoute with a wrong namesake", () => {
  it("searches a far-off stop again near the line between its neighbors and, finding nothing, places it there as uncertain", async () => {
    const wrong: GeoPoint = { lat: 34.53, lng: 134.99 };
    const lookup: Lookup = async (place, c) => {
      const hit = place === "Wakayama" ? WAKAYAMA : ({ A: { lat: 34.25, lng: 135.11 }, Temple: wrong, B: { lat: 34.27, lng: 135.12 }, C: { lat: 34.29, lng: 135.15 } } as Record<string, GeoPoint>)[place];
      if (!hit) return null;
      const b = c.bounds;
      return b && (hit.lng < b.west || hit.lng > b.east || hit.lat < b.south || hit.lat > b.north) ? null : hit;
    };
    const out = await geocodeRoute(["A, Wakayama", "Temple, Wakayama", "B, Wakayama", "C, Wakayama"], { lookup });
    expect(out.found[1].uncertain).toBe(true);
    expect(distanceKm(out.found[1].point, out.found[0].point)).toBeLessThan(5);
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
