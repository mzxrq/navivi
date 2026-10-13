import { describe, expect, it } from "vitest";
import { parseCoordinates } from "../../src/utils/coordinates";

describe("parseCoordinates", () => {
  it("reads latitude and longitude separated by a comma or a space", () => {
    expect(parseCoordinates("34.2908, 135.1508")).toEqual([34.2908, 135.1508]);
    expect(parseCoordinates("  -33.5 151.2 ")).toEqual([-33.5, 151.2]);
  });

  it("rejects text that is not a pair or is out of range", () => {
    expect(parseCoordinates("")).toBeNull();
    expect(parseCoordinates("34.29")).toBeNull();
    expect(parseCoordinates("91, 10")).toBeNull();
    expect(parseCoordinates("10, 181")).toBeNull();
    expect(parseCoordinates("north, east")).toBeNull();
  });
});
