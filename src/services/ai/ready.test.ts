import { describe, expect, it } from "vitest";
import { aiReady } from "./ready";

describe("aiReady", () => {
  it("is off when AI features are off", () => {
    expect(aiReady({ ai_features_enabled: false, ai_provider: "openrouter" }, [], true)).toBe(false);
  });

  it("needs a saved key for an online provider", () => {
    expect(aiReady({ ai_features_enabled: true, ai_provider: "openrouter" }, [], false)).toBe(false);
    expect(aiReady({ ai_features_enabled: true, ai_provider: "openrouter" }, [], true)).toBe(true);
  });

  it("needs an address for the custom provider", () => {
    expect(aiReady({ ai_provider: "custom" }, [], true)).toBe(false);
    expect(aiReady({ ai_provider: "custom", ai_online_base_url: "https://x.test/v1" }, [], true)).toBe(true);
  });

  it("needs the chosen model installed locally, or the default one", () => {
    expect(aiReady({ ai_model: "gemma4" }, ["llama3.2"], false)).toBe(false);
    expect(aiReady({ ai_model: "gemma4" }, ["gemma4"], false)).toBe(true);
    expect(aiReady({}, ["schroneko/gemma-2-2b-jpn-it"], false)).toBe(true);
    expect(aiReady({}, [], false)).toBe(false);
  });
});
