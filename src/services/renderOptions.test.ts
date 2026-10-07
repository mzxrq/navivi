import { expect, it } from "vitest";
import { requestForcedRender, takeForcedRender } from "./renderOptions";

it("is read once, so a retry does not force again", () => {
  expect(takeForcedRender()).toBe(false);
  requestForcedRender(true);
  expect(takeForcedRender()).toBe(true);
  expect(takeForcedRender()).toBe(false);
});
