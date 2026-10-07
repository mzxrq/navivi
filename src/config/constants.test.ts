import { describe, expect, it } from "vitest";
import { defaultProjectSettings } from "./constants";

describe("defaultProjectSettings", () => {
  it("leaves the pin size to the renderer's own default", () => {
    expect(defaultProjectSettings).not.toHaveProperty("marker_radius");
  });
});
