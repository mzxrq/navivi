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
  mocks.settingsPut.mockReset().mockImplementation((_id: string, settings: unknown) => Promise.resolve(settings));
});

const save = async (extra: Record<string, unknown>) => {
  await saveProjectData([], [], { project_id: "kyoto", project_name: "Kyoto", directory_path: "C:/p", ...extra } as any, {}, {});
  return JSON.parse(mocks.written["C:/p/job_config.json"]);
};

describe("saving the overview narration", () => {
  it("keeps a script the user wrote, marked as not auto", async () => {
    const config = await save({ overview_narration: "自分の案内です。", overview_narration_is_auto: false });
    expect(config.overview_narration).toBe("自分の案内です。");
    expect(config.overview_narration_is_auto).toBe(false);
  });

  it("keeps an auto script with the stops it was written for", async () => {
    const config = await save({ overview_narration: "{start}案内", overview_narration_is_auto: true, overview_narration_source_ids: "a,b" });
    expect(config).toMatchObject({ overview_narration: "{start}案内", overview_narration_is_auto: true, overview_narration_source_ids: "a,b" });
  });

  it("writes a blank field for a project without one, as before", async () => {
    const config = await save({});
    expect(config.overview_narration).toBe("");
    expect(config).not.toHaveProperty("overview_narration_is_auto");
  });
});
