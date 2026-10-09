import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ written: {} as Record<string, string>, settingsPut: vi.fn() }));

vi.mock("@tauri-apps/api/path", () => ({
  documentDir: () => Promise.resolve("C:/Docs"),
  join: (...p: string[]) => Promise.resolve(p.join("/")),
  basename: (p: string) => Promise.resolve(p.split("/").pop()),
  dirname: (p: string) => Promise.resolve(p.split("/").slice(0, -1).join("/")),
}));
vi.mock("@tauri-apps/plugin-fs", () => ({
  writeTextFile: (path: string, text: string) => Promise.resolve(void (mocks.written[path] = text)),
  writeFile: vi.fn(),
  mkdir: vi.fn(),
  exists: () => Promise.resolve(true),
  copyFile: vi.fn(),
  readTextFile: vi.fn(),
  readDir: vi.fn(),
  open: vi.fn(),
  BaseDirectory: {},
}));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(), convertFileSrc: (p: string) => p }));
vi.mock("@lingui/core", () => ({ i18n: { locale: "en" } }));
vi.mock("./db", () => ({
  db: {
    projects: {
      get: vi.fn(() => Promise.resolve(null)),
      upsert: vi.fn((input: any) => Promise.resolve({ ...input, userId: null, createdAt: "t", updatedAt: 1, videoTitle: "", videoSubtitle: "", enableIntro: true })),
    },
    settings: { put: mocks.settingsPut },
    appSettings: { get: vi.fn(() => Promise.resolve(null)) },
    routeCache: { replace: vi.fn() },
  },
}));

import { saveProjectData } from "./fileSystem";

beforeEach(() => {
  mocks.written = {};
  // The backend hands back what it stored.
  mocks.settingsPut.mockReset().mockImplementation((_id: string, settings: unknown) => Promise.resolve(settings));
});

describe("saving a project", () => {
  it("never writes the map keys to the database row or to job_config.json", async () => {
    const settings = { fps: 30, mapbox_api_key: "pk.secret", ors_api_key: "ors-secret" };
    await saveProjectData([], [], { project_id: "kyoto", project_name: "Kyoto", directory_path: "C:/p" }, settings, {});

    expect(mocks.settingsPut).toHaveBeenCalledTimes(1);
    expect(mocks.settingsPut.mock.calls[0][1]).toEqual({ fps: 30, follow_editor_map_style: true, mapbox_style_id: "mapbox/outdoors-v12" });

    const config = mocks.written["C:/p/job_config.json"];
    expect(config).toBeDefined();
    expect(config).not.toContain("pk.secret");
    expect(config).not.toContain("ors-secret");
    expect(JSON.parse(config).settings.fps).toBe(30);
    // The caller's object is untouched: the app still needs the keys.
    expect(settings.mapbox_api_key).toBe("pk.secret");
  });

  it("drops keys even when the backend echoes them back from an old row", async () => {
    mocks.settingsPut.mockImplementation((_id: string, settings: any) => Promise.resolve({ ...settings, mapbox_api_key: "pk.stale" }));
    await saveProjectData([], [], { project_id: "kyoto", project_name: "Kyoto", directory_path: "C:/p" }, { fps: 30 }, {});
    expect(mocks.written["C:/p/job_config.json"]).not.toContain("pk.stale");
  });
});
