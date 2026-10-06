import { describe, expect, it } from "vitest";
import { savedImages } from "./waypointImages";

describe("savedImages", () => {
  it("returns every photo when images holds more than popup_image", () => {
    expect(savedImages({ popup_image: ["a.jpg"], images: ["a.jpg", "b.jpg"] })).toEqual(["a.jpg", "b.jpg"]);
  });

  it("falls back to popup_image for projects saved before images existed", () => {
    expect(savedImages({ popup_image: ["a.jpg"] })).toEqual(["a.jpg"]);
    expect(savedImages({ popup_image: ["a.jpg"], images: [] })).toEqual(["a.jpg"]);
  });

  it("is empty when neither has a photo, even when both are empty arrays", () => {
    expect(savedImages({ popup_image: [], images: [] })).toEqual([]);
    expect(savedImages({})).toEqual([]);
  });
});
