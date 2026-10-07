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

const saveStops = async (stops: Record<string, unknown>[], settings: Record<string, unknown> = {}) => {
  const waypoints = stops.map((s, i) => ({ id: `w${i}`, lat: 35 + i, lng: 135, name: `Stop ${i}`, routeMode: "walking", ...s }));
  await saveProjectData(waypoints, [], { project_id: "kyoto", project_name: "Kyoto", directory_path: "C:/p" } as any, settings, {});
  return JSON.parse(mocks.written["C:/p/job_config.json"]);
};

describe("saving the per-stop look options", () => {
  it("writes the card look and the overview opt-out", async () => {
    const config = await saveStops([{ imageDisplay: "cover", overviewHighlight: false }, {}]);
    expect(config.waypoints[0]).toMatchObject({ image_display: "cover", overviewHighlight: false });
  });

  it("leaves a stop without the options exactly as before", async () => {
    const config = await saveStops([{}, {}]);
    expect(config.waypoints[0].image_display).toBe("pip");
    expect(config.waypoints[0]).not.toHaveProperty("overviewHighlight");
  });

  it("keeps the project's look settings in the file", async () => {
    const config = await saveStops([{}], { enable_outro: false, mode_line_colors: { ferry: [1, 2, 3] }, start_pin_color: [9, 9, 9] });
    expect(config.settings).toMatchObject({ enable_outro: false, mode_line_colors: { ferry: [1, 2, 3] }, start_pin_color: [9, 9, 9] });
  });
});
