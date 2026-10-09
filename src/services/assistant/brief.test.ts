import { describe, expect, it } from "vitest";
import { detectLanguage } from "./brief";

describe("detectLanguage", () => {
  it("calls an English trail guide English even with a few Japanese names", () => {
    expect(detectLanguage("Leave Kyoshi Station and follow the road to Kosen-ji Temple (光泉寺). The climb takes 1 hr. 20 min.")).toBe("en");
  });
  it("calls Japanese text Japanese", () => {
    expect(detectLanguage("京子駅を出て、左に曲がり、線路沿いに進みます。光泉寺は孝子観音で知られています。")).toBe("ja");
  });
});
