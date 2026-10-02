import { describe, expect, it } from "vitest";
import { modelFit } from "./modelFit";

const GB = 1024 ** 3;

describe("modelFit", () => {
  it("flags a model that needs more memory than the PC can spare (17 GB on a 15 GB PC)", () => {
    const fit = modelFit(17 * GB, 15.3)!;
    expect(fit.tooBig).toBe(true);
    expect(fit.sizeGb).toBeCloseTo(17, 1);
    expect(fit.ramGb).toBe(15.3);
  });

  it("leaves small models alone", () => {
    expect(modelFit(2 * GB, 15.3)!.tooBig).toBe(false);
    expect(modelFit(5.4 * GB, 15.3)!.tooBig).toBe(false);
  });

  it("is about the share of memory, so the same model is fine on a bigger PC", () => {
    expect(modelFit(17 * GB, 32)!.tooBig).toBe(false);
    expect(modelFit(9.5 * GB, 15.3)!.tooBig).toBe(true);
    expect(modelFit(9 * GB, 15.3)!.tooBig).toBe(false);
  });

  it("says nothing when it does not know the size or the memory", () => {
    expect(modelFit(undefined, 15.3)).toBeNull();
    expect(modelFit(2 * GB, undefined)).toBeNull();
    expect(modelFit(0, 15.3)).toBeNull();
  });
});
