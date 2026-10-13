import { describe, expect, it } from "vitest";
import { defaultProjectSettings } from "../../src/config/constants";

describe("defaultProjectSettings", () => {
  it("leaves the pin size to the renderer's own default", () => {
    expect(defaultProjectSettings).not.toHaveProperty("marker_radius");
  });
});
