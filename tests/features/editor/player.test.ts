import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/api/core", () => ({ convertFileSrc: (p: string) => `asset://${p}` }));

import { mediaUrl, refreshMedia } from "../../../src/features/editor/player";

describe("mediaUrl", () => {
  it("changes after a new render, so a re-made clip with the same file name loads again", async () => {
    const before = mediaUrl("C:/p", "assets/video/a.mp4");
    expect(before.startsWith("asset://C:/p/assets/video/a.mp4?v=")).toBe(true);
    await new Promise((r) => setTimeout(r, 2));
    refreshMedia();
    expect(mediaUrl("C:/p", "assets/video/a.mp4")).not.toBe(before);
    expect(mediaUrl("C:/p", "")).toBe("");
  });
});
