import path from "node:path";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ invoke: vi.fn(), exists: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("@tauri-apps/plugin-fs", () => ({ exists: mocks.exists }));
vi.mock("@tauri-apps/api/path", () => ({ basename: async (p: string) => path.win32.basename(p) }));

import { importAssets } from "../../src/utils/fileNames";

describe("importAssets", () => {
  beforeEach(() => {
    mocks.invoke.mockReset();
    mocks.exists.mockReset().mockResolvedValue(true);
  });

  it("copies one file at a time and uses the name copy_asset_file chose", async () => {
    let running = 0;
    mocks.invoke.mockImplementation(async (_cmd: string, { sourcePath }: { sourcePath: string }) => {
      expect(++running).toBe(1);
      await new Promise((r) => setTimeout(r, 1));
      running--;
      return sourcePath.startsWith("D:/a") ? "C:/p/v/GX01.MP4" : "C:/p/v/GX01 (2).MP4";
    });
    const names = await importAssets("C:/p/v", ["D:/a/GX01.MP4", "E:/b/GX01.MP4", "D:/a/GX01.MP4"]);
    expect(mocks.invoke).toHaveBeenCalledTimes(2);
    expect(names.get("D:/a/GX01.MP4")).toBe("GX01.MP4");
    expect(names.get("E:/b/GX01.MP4")).toBe("GX01 (2).MP4");
  });

  it("does not compare a file again on the next save, unless its copy is gone", async () => {
    mocks.invoke.mockResolvedValue("C:/q/v/clip.mp4");
    await importAssets("C:/q/v", ["D:/clip.mp4"]);
    await importAssets("C:/q/v", ["D:/clip.mp4"]);
    expect(mocks.invoke).toHaveBeenCalledTimes(1);
    mocks.exists.mockResolvedValue(false);
    await importAssets("C:/q/v", ["D:/clip.mp4"]);
    expect(mocks.invoke).toHaveBeenCalledTimes(2);
  });
});
