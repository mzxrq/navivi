import { beforeEach, describe, expect, it, vi } from "vitest";

const callSidecar = vi.hoisted(() => vi.fn());
vi.mock("./sidecar", () => ({ callSidecar }));
vi.mock("@tauri-apps/api/path", () => ({
  documentDir: async () => "C:/Users/me/Documents",
  join: async (...parts: string[]) => parts.join("/"),
}));

import { isHeic, isPhoto, preparePhotos } from "./imageImport";

beforeEach(() => {
  callSidecar.mockReset();
});

describe("file types", () => {
  it("recognises iPhone photos in any case, and the formats the app already took", () => {
    expect(["a.HEIC", "b.heif", "c.Heic"].every(isHeic)).toBe(true);
    expect(["a.jpg", "b.JPEG", "c.png", "d.heic"].every(isPhoto)).toBe(true);
    expect(["a.gif", "b.pdf", "heic"].some(isPhoto)).toBe(false);
  });
});

describe("preparePhotos", () => {
  it("does not start the converter when there is no HEIC photo", async () => {
    const paths = ["D:/a.jpg", "D:/b.png"];
    await expect(preparePhotos(paths)).resolves.toEqual({ paths, converted: 0, failed: [] });
    expect(callSidecar).not.toHaveBeenCalled();
  });

  it("swaps each HEIC photo for its JPEG and keeps the order", async () => {
    callSidecar.mockResolvedValue({ success: true, images: { "D:/b.HEIC": "C:/Imports/b.jpg", "D:/d.heif": "C:/Imports/d.jpg" }, failed: {} });
    const out = await preparePhotos(["D:/a.jpg", "D:/b.HEIC", "D:/c.png", "D:/d.heif"]);
    expect(out).toEqual({ paths: ["D:/a.jpg", "C:/Imports/b.jpg", "D:/c.png", "C:/Imports/d.jpg"], converted: 2, failed: [] });
  });

  it("sends only the HEIC photos, with a fresh folder under Documents/Navivi/Imports", async () => {
    callSidecar.mockResolvedValue({ success: true, images: { "D:/b.heic": "x.jpg" }, failed: {} });
    await preparePhotos(["D:/a.jpg", "D:/b.heic"]);
    const [mode, input] = callSidecar.mock.calls[0];
    expect(mode).toBe("convert_images");
    expect(input.paths).toEqual(["D:/b.heic"]);
    expect(input.out_dir).toMatch(/^C:\/Users\/me\/Documents\/.+\/Imports\/\d+$/);
  });

  it("leaves out a photo that could not be converted and says which", async () => {
    callSidecar.mockResolvedValue({ success: true, images: { "D:/good.heic": "C:/Imports/good.jpg" }, failed: { "D:/bad.heic": "UnidentifiedImageError" } });
    const out = await preparePhotos(["D:/good.heic", "D:/bad.heic", "D:/c.jpg"]);
    expect(out.paths).toEqual(["C:/Imports/good.jpg", "D:/c.jpg"]);
    expect(out.failed).toEqual(["D:/bad.heic"]);
    expect(out.converted).toBe(1);
  });

  it("throws the converter's own message when it cannot run", async () => {
    callSidecar.mockResolvedValue({ success: false, error: "HEIC photos need the pillow-heif package. Install it with: pip install pillow-heif" });
    await expect(preparePhotos(["D:/a.heic"])).rejects.toThrow("pip install pillow-heif");
  });

  it("explains a conversion that another sidecar call interrupted", async () => {
    callSidecar.mockResolvedValue({ success: false, error: "Process was cancelled", cancelled: true });
    await expect(preparePhotos(["D:/a.heic"])).rejects.toThrow(/interrupted/);
  });
});
