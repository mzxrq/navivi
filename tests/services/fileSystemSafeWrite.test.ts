import { beforeEach, describe, expect, it, vi } from "vitest";

const disk_ = vi.hoisted(() => ({ disk: new Map<string, string>(), failRenames: 0 }));
vi.mock("@tauri-apps/plugin-fs", () => ({
  writeTextFile: async (p: string, text: string) => void disk_.disk.set(p, text),
  rename: async (from: string, to: string) => {
    if (disk_.failRenames-- > 0) throw new Error("file in use");
    disk_.disk.set(to, disk_.disk.get(from)!);
    disk_.disk.delete(from);
  },
}));
vi.mock("@tauri-apps/api/path", () => ({ join: async (...p: string[]) => p.join("/") }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(), convertFileSrc: (p: string) => p }));
vi.mock("@lingui/core", () => ({ i18n: { locale: "en" } }));
vi.mock("../../src/services/db", () => ({ db: {} }));

import { writeFileSafely } from "../../src/services/fileSystem";

describe("writeFileSafely", () => {
  beforeEach(() => {
    disk_.disk.clear();
    disk_.failRenames = 0;
  });

  it("only replaces the file once the new text is written in full", async () => {
    disk_.disk.set("t.json", "old");
    await writeFileSafely("t.json", "new");
    expect(disk_.disk.get("t.json")).toBe("new");
    expect(disk_.disk.has("t.json.tmp")).toBe(false);
  });

  it("retries a rename the system refuses for a moment", async () => {
    disk_.failRenames = 2;
    await writeFileSafely("t.json", "new");
    expect(disk_.disk.get("t.json")).toBe("new");
  });
});
