import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  row: { id: "kyoto", name: "Kyoto", userId: null, theme: null, createdAt: "t", videoTitle: "", videoSubtitle: "", enableIntro: true, updatedAt: 5, directoryPath: "C:/p" },
  dbSettings: null as Record<string, unknown> | null,
  put: vi.fn(),
  importLegacy: vi.fn(),
  get: vi.fn(),
}));

vi.mock("@tauri-apps/api/path", () => ({ join: (...p: string[]) => Promise.resolve(p.join("/")) }));
vi.mock("./fileSystem", () => ({ duplicateProjectFolder: vi.fn(), loadProjectData: vi.fn(), loadRouteCache: vi.fn(() => Promise.resolve({})) }));
vi.mock("./versionHistory", () => ({ readLegacyHistory: vi.fn(() => Promise.resolve([])) }));
vi.mock("./db", () => ({
  db: {
    projects: {
      get: mocks.get,
      importLegacy: mocks.importLegacy,
      upsert: vi.fn(() => Promise.resolve(mocks.row)),
      update: vi.fn(() => Promise.resolve(mocks.row)),
      touchOpened: vi.fn(() => Promise.resolve(mocks.row)),
    },
    settings: { get: vi.fn(() => Promise.resolve(mocks.dbSettings)), put: mocks.put },
    routeCache: { getAll: vi.fn(() => Promise.resolve({})), replace: vi.fn() },
  },
}));

import { syncProjectOnOpen } from "./projectStore";

const jobConfig = (settings: Record<string, unknown>) => ({
  project_id: "kyoto",
  project_name: "Kyoto",
  directory_path: "C:/p",
  updated_at: 1,
  settings,
});

beforeEach(() => {
  mocks.dbSettings = null;
  mocks.put.mockReset().mockResolvedValue({});
  mocks.importLegacy.mockReset().mockResolvedValue({ project: mocks.row });
  mocks.get.mockReset().mockResolvedValue(mocks.row);
});

describe("opening a project saved before the keys became app-wide", () => {
  it("reports the keys from the file and returns settings without them", async () => {
    mocks.dbSettings = null;
    const out = await syncProjectOnOpen(jobConfig({ fps: 30, mapbox_api_key: "pk.file", ors_api_key: "o" }), "C:/p");
    expect(out.legacyApiKeys).toEqual({ mapbox: "pk.file", ors: "o" });
    expect(out.data.settings).toEqual({ fps: 30 });
  });

  it("removes the keys from the database row and reports them", async () => {
    mocks.dbSettings = { fps: 24, mapbox_api_key: "pk.db" };
    const out = await syncProjectOnOpen(jobConfig({ fps: 24 }), "C:/p");
    expect(mocks.put).toHaveBeenCalledWith("kyoto", { fps: 24 });
    expect(out.legacyApiKeys).toEqual({ mapbox: "pk.db" });
    expect(out.data.settings).toEqual({ fps: 24 });
  });

  it("never stores the keys when a new project row is imported", async () => {
    mocks.get.mockResolvedValue(null);
    await syncProjectOnOpen(jobConfig({ fps: 30, mapbox_api_key: "pk.file" }), "C:/p");
    expect(mocks.importLegacy.mock.calls[0][0].settings).toEqual({ fps: 30 });
  });

  it("a project without keys reports none and writes nothing to the settings row", async () => {
    mocks.dbSettings = { fps: 30 };
    const out = await syncProjectOnOpen(jobConfig({ fps: 30 }), "C:/p");
    expect(out.legacyApiKeys).toEqual({});
    expect(mocks.put).not.toHaveBeenCalled();
  });
});
