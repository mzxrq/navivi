import path from "node:path";
import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/path", () => ({
  basename: async (p: string) => path.win32.basename(p),
  join: async (...parts: string[]) => path.win32.join(...parts),
}));

import { planFileNames } from "./fileNames";

const dir = "C:/p/assets/image";

describe("planFileNames", () => {
  it("keeps the name of a file nobody else shares", async () => {
    const plan = await planFileNames(dir, ["D:/photos/solo.jpg"]);
    expect(plan.get("D:/photos/solo.jpg")).toBe("solo.jpg");
  });

  it("gives two different files with the same name different names", async () => {
    const plan = await planFileNames(dir, ["D:/a/IMG_0001.jpg", "D:/b/IMG_0001.jpg"]);
    const [a, b] = [plan.get("D:/a/IMG_0001.jpg"), plan.get("D:/b/IMG_0001.jpg")];
    expect(a).not.toBe(b);
    expect(a).toMatch(/^IMG_0001-\w+\.jpg$/);
    expect(b).toMatch(/^IMG_0001-\w+\.jpg$/);
  });

  it("does not depend on the order of the stops", async () => {
    const forward = await planFileNames(dir, ["D:/a/IMG.jpg", "D:/b/IMG.jpg"]);
    const backward = await planFileNames(dir, ["D:/b/IMG.jpg", "D:/a/IMG.jpg"]);
    expect(backward.get("D:/a/IMG.jpg")).toBe(forward.get("D:/a/IMG.jpg"));
    expect(backward.get("D:/b/IMG.jpg")).toBe(forward.get("D:/b/IMG.jpg"));
  });

  it("keeps the name of a file already in the folder and moves a newcomer out of its way", async () => {
    const plan = await planFileNames(dir, ["D:/x/IMG.jpg", "C:/p/assets/image/IMG.jpg"]);
    expect(plan.get("C:/p/assets/image/IMG.jpg")).toBe("IMG.jpg");
    expect(plan.get("D:/x/IMG.jpg")).not.toBe("IMG.jpg");
  });

  it("treats the same path twice, or with another slash style or case, as one file", async () => {
    const plan = await planFileNames(dir, ["D:/a/same.jpg", "D:/a/same.jpg", "C:/P/Assets/Image/Own.JPG"]);
    expect(plan.size).toBe(2);
    expect(plan.get("D:/a/same.jpg")).toBe("same.jpg");
    expect(plan.get("C:/P/Assets/Image/Own.JPG")).toBe("Own.JPG");
  });

  it("never hands out one name twice", async () => {
    const sources = ["D:/a/x.png", "D:/b/x.png", "D:/c/x.png", "C:/p/assets/image/x.png"];
    const names = [...(await planFileNames(dir, sources)).values()].map((n) => n.toLowerCase());
    expect(new Set(names).size).toBe(sources.length);
  });
});
