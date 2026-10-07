import { describe, expect, it } from "vitest";
import {
  adoptLegacyKeys,
  apiKeySettings,
  cleanApiKeys,
  hasApiKeys,
  legacyApiKeys,
  patchedApiKeys,
  sameApiKeys,
  stripApiKeys,
} from "./apiKeys";

describe("map keys are the app's, not a project's", () => {
  it("stripApiKeys drops both keys and nothing else, without touching the original", () => {
    const settings = { fps: 30, mapbox_api_key: "pk.a", ors_api_key: "ors" };
    expect(stripApiKeys(settings)).toEqual({ fps: 30 });
    expect(settings.mapbox_api_key).toBe("pk.a");
  });

  it("legacyApiKeys finds what an old project carries and ignores empty values", () => {
    expect(legacyApiKeys({ mapbox_api_key: "pk.a", ors_api_key: "  " })).toEqual({ mapbox: "pk.a" });
    expect(legacyApiKeys(null)).toEqual({});
    expect(legacyApiKeys({ mapbox_api_key: 5 })).toEqual({});
  });

  it("patchedApiKeys keeps an empty string, because that is the user clearing a key", () => {
    expect(patchedApiKeys({ mapbox_api_key: "" })).toEqual({ mapbox: "" });
    expect(patchedApiKeys({ fps: 24 })).toEqual({});
  });

  it("cleanApiKeys reduces whatever the database held to the two string fields", () => {
    expect(cleanApiKeys({ mapbox: "m", ors: 3, other: "x" })).toEqual({ mapbox: "m" });
    expect(cleanApiKeys("junk")).toEqual({});
    expect(cleanApiKeys(null)).toEqual({});
  });

  it("apiKeySettings gives the fields the UI reads, empty when unset", () => {
    expect(apiKeySettings({ mapbox: "m" })).toEqual({ mapbox_api_key: "m", ors_api_key: "" });
  });
});

describe("adopting the keys of an old project", () => {
  it("fills only what is still empty and never replaces a key the user already has", () => {
    expect(adoptLegacyKeys({}, { mapbox: "old", ors: "o" })).toEqual({ mapbox: "old", ors: "o" });
    expect(adoptLegacyKeys({ mapbox: "mine" }, { mapbox: "old", ors: "o" })).toEqual({ mapbox: "mine", ors: "o" });
    expect(adoptLegacyKeys({ mapbox: "" }, { mapbox: "old" })).toEqual({ mapbox: "old" });
  });

  it("hasApiKeys and sameApiKeys treat a missing key like an empty one", () => {
    expect(hasApiKeys({ mapbox: " " })).toBe(false);
    expect(hasApiKeys({ ors: "k" })).toBe(true);
    expect(sameApiKeys({ mapbox: "" }, {})).toBe(true);
    expect(sameApiKeys({ mapbox: "a" }, {})).toBe(false);
  });
});
