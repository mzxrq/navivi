// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const store = vi.hoisted(() => ({ records: {} as Record<string, unknown>, get: vi.fn(), set: vi.fn() }));

vi.mock("@tauri-apps/api/window", () => ({ getCurrentWindow: () => ({ onCloseRequested: () => Promise.resolve(() => {}), destroy: vi.fn() }) }));
vi.mock("../services/db", () => ({
  db: {
    appSettings: { get: store.get, set: store.set, delete: vi.fn(), list: vi.fn() },
    projects: {},
    settings: {},
    versions: {},
    routeCache: {},
  },
}));
vi.mock("../services/fileSystem", () => ({
  saveProjectData: vi.fn(), loadProjectData: vi.fn(), scanProjectsOnDisk: vi.fn(() => Promise.resolve([])), loadTimelineData: vi.fn(),
  loadRouteCache: vi.fn(), tidyProjectFolder: vi.fn(), saveTimelineManifest: vi.fn(),
}));
vi.mock("../services/versionHistory", () => ({ deleteProjectVersion: vi.fn(), listProjectVersions: vi.fn(() => Promise.resolve([])), loadProjectVersion: vi.fn(), saveProjectVersion: vi.fn() }));
vi.mock("../services/projectStore", () => ({ listRecents: vi.fn(() => Promise.resolve([])), syncProjectOnOpen: vi.fn() }));
vi.mock("./useUI", () => ({ useUI: () => ({ editorMode: "map", isRendering: false, isBackgroundRender: false, showToast: vi.fn(), setCurrentView: vi.fn() }) }));
vi.mock("../components/ui/UnsavedChanges", () => ({ UnsavedChanges: () => null }));

import { useWorkspace, WorkspaceProvider } from "./useWorkspace";

const wrapper = ({ children }: { children: ReactNode }) => <WorkspaceProvider>{children}</WorkspaceProvider>;
const keyWrites = () => store.set.mock.calls.filter(([key]) => key === "api_keys").map(([, value]) => value);

beforeEach(() => {
  store.records = {};
  store.get.mockReset().mockImplementation((key: string) => Promise.resolve(store.records[key] ?? null));
  store.set.mockReset().mockResolvedValue(undefined);
});

describe("the Mapbox and OpenRouteService keys live in the app settings", () => {
  it("come back from the database into the merged settings", async () => {
    store.records.api_keys = { mapbox: "pk.saved", ors: "ors-saved" };
    const { result } = renderHook(() => useWorkspace(), { wrapper });
    await waitFor(() => expect(result.current.settings.mapbox_api_key).toBe("pk.saved"));
    expect(result.current.settings.ors_api_key).toBe("ors-saved");
  });

  it("are saved as api_keys when the user types one, and do not make the project dirty", async () => {
    const { result } = renderHook(() => useWorkspace(), { wrapper });
    await act(async () => {});
    act(() => result.current.updateSettings({ mapbox_api_key: "pk.typed" }));
    expect(keyWrites()[keyWrites().length - 1]).toEqual({ mapbox: "pk.typed" });
    expect(result.current.settings.mapbox_api_key).toBe("pk.typed");
    expect(result.current.isDirty).toBe(false);
  });

  it("are not taken from a project's settings object", async () => {
    store.records.api_keys = { mapbox: "pk.app" };
    const { result } = renderHook(() => useWorkspace(), { wrapper });
    await waitFor(() => expect(result.current.settings.mapbox_api_key).toBe("pk.app"));
    act(() => result.current.setSettings({ ...result.current.settings, mapbox_api_key: "pk.project", ors_api_key: "ors.project" } as never));
    expect(result.current.settings.mapbox_api_key).toBe("pk.app");
    expect(result.current.settings.ors_api_key).toBe("");
  });

  it("a change made before the saved record is read waits, then wins without losing the other saved key", async () => {
    let finish: (v: unknown) => void = () => {};
    store.get.mockImplementation((key: string) => (key === "api_keys" ? new Promise((resolve) => (finish = resolve)) : Promise.resolve(null)));
    const { result } = renderHook(() => useWorkspace(), { wrapper });
    act(() => result.current.updateSettings({ mapbox_api_key: "pk.early" }));
    expect(keyWrites()).toHaveLength(0);
    await act(async () => finish({ mapbox: "pk.old", ors: "ors-saved" }));
    await waitFor(() => expect(keyWrites()[keyWrites().length - 1]).toEqual({ mapbox: "pk.early", ors: "ors-saved" }));
    expect(result.current.settings.mapbox_api_key).toBe("pk.early");
  });
});
