// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const store = vi.hoisted(() => ({ saved: null as unknown, get: vi.fn(), set: vi.fn() }));

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

beforeEach(() => {
  store.get.mockReset();
  store.set.mockReset().mockResolvedValue(undefined);
});

describe("the AI choice is remembered between launches", () => {
  it("comes back from the database when the app starts", async () => {
    store.get.mockResolvedValue({ ai_provider: "openrouter", ai_online_models: { openrouter: "anthropic/claude-haiku-4.5" }, ai_features_enabled: true });
    const { result } = renderHook(() => useWorkspace(), { wrapper });
    await waitFor(() => expect(result.current.settings.ai_provider).toBe("openrouter"));
    expect(result.current.settings.ai_online_models?.openrouter).toBe("anthropic/claude-haiku-4.5");
  });

  it("is written to the database when the user picks a provider", async () => {
    store.get.mockResolvedValue(null);
    const { result } = renderHook(() => useWorkspace(), { wrapper });
    await waitFor(() => expect(store.get).toHaveBeenCalled());
    await act(async () => {});
    act(() => result.current.updateSettings({ ai_provider: "openrouter" }));
    expect(store.set).toHaveBeenCalledWith("ai_settings", expect.objectContaining({ ai_provider: "openrouter", ai_features_enabled: true }));
  });

  it("is not overwritten by what a project file says", async () => {
    store.get.mockResolvedValue({ ai_provider: "openrouter" });
    const { result } = renderHook(() => useWorkspace(), { wrapper });
    await waitFor(() => expect(result.current.settings.ai_provider).toBe("openrouter"));
    act(() => result.current.setSettings({ ...result.current.settings, ai_provider: "ollama" } as never));
    expect(result.current.settings.ai_provider).toBe("openrouter");
  });

  it("a change made before the saved choice is read does not wipe the rest of the saved record", async () => {
    let finish: (v: unknown) => void = () => {};
    store.get.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const { result } = renderHook(() => useWorkspace(), { wrapper });
    act(() => result.current.updateSettings({ ai_features_enabled: true }));
    expect(store.set).not.toHaveBeenCalled();
    await act(async () => finish({ ai_provider: "openrouter", ai_online_models: { openrouter: "x/y" } }));
    await waitFor(() => expect(store.set).toHaveBeenCalledWith("ai_settings", expect.objectContaining({ ai_provider: "openrouter", ai_features_enabled: true })));
    expect(result.current.settings.ai_provider).toBe("openrouter");
  });

  it("reads the saved choice again when the first read fails", async () => {
    vi.useFakeTimers();
    store.get.mockRejectedValueOnce(new Error("database is locked")).mockResolvedValue({ ai_provider: "openrouter" });
    vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useWorkspace(), { wrapper });
    await act(async () => { await vi.advanceTimersByTimeAsync(1100); });
    vi.useRealTimers();
    expect(result.current.settings.ai_provider).toBe("openrouter");
  });
});
