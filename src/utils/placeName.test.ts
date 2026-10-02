import { describe, expect, it } from "vitest";
import { placeNameOf } from "./placeName";

describe("placeNameOf", () => {
  it("prefers the place's own name, then its street", () => {
    expect(placeNameOf({ name: "Awashima Shrine", address: { road: "Route 1", city: "Wakayama" } }, "x")).toBe("Awashima Shrine");
    expect(placeNameOf({ name: "", address: { road: "Route 1", city: "Wakayama" } }, "x")).toBe("Route 1");
  });

  it("calls a nameless spot after its neighbourhood, not its city", () => {
    expect(placeNameOf({ name: "", address: { quarter: "加太", city: "和歌山市", province: "和歌山県" } }, "x")).toBe("加太");
    expect(placeNameOf({ address: { suburb: "Kada", city: "Wakayama" } }, "x")).toBe("Kada");
  });

  it("takes the smallest area when there are several", () => {
    expect(placeNameOf({ address: { city: "City", village: "Village", hamlet: "Hamlet" } }, "x")).toBe("Hamlet");
  });

  it("uses the city when it is all there is, and the fallback when there is nothing", () => {
    expect(placeNameOf({ address: { city: "Wakayama" } }, "x")).toBe("Wakayama");
    expect(placeNameOf({ address: { country: "Japan" } }, "Stop")).toBe("Stop");
    expect(placeNameOf({ error: "Unable to geocode" }, "Stop")).toBe("Stop");
    expect(placeNameOf(null, "Stop")).toBe("Stop");
  });
});
