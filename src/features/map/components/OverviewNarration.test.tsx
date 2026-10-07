// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sidecar = vi.hoisted(() => ({ callSidecar: vi.fn(), callSidecarShared: vi.fn() }));
const workspace = vi.hoisted(() => ({
  metadata: {} as Record<string, unknown>,
  settings: {},
  updateMetadata: vi.fn(),
  updateSettings: vi.fn(),
  setIsDirty: vi.fn(),
  saveProject: vi.fn(),
}));
vi.mock("../../../services/sidecar", () => sidecar);
vi.mock("../../../hooks/useWorkspace", () => ({ useWorkspace: () => workspace }));
vi.mock("../../../hooks/useUI", () => ({ useUI: () => ({ showToast: vi.fn(), isRendering: false }) }));
vi.mock("../../../services/ollamaApi", () => ({ warmUpModel: vi.fn() }));
vi.mock("../../../services/ai/engine", () => ({ aiEngine: () => "ollama" }));
vi.mock("@tauri-apps/api/core", () => ({ convertFileSrc: (p: string) => p }));

import { OverviewNarration } from "./OverviewNarration";

i18n.load("en", {});
i18n.activate("en");

const LIMITS = { chars_per_second: 5, target_seconds: 90, min_seconds: 60, max_seconds: 120 };
const CONFIG = "C:/p/job_config.json";

const show = async () => {
  render(
    <I18nProvider i18n={i18n}>
      <OverviewNarration />
    </I18nProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: /Overview narration/ }));
};

beforeEach(() => {
  workspace.metadata = { directory_path: "C:/p" };
  workspace.updateMetadata.mockReset();
  workspace.saveProject.mockReset().mockResolvedValue(undefined);
  sidecar.callSidecar.mockReset();
  sidecar.callSidecarShared.mockReset().mockResolvedValue({ success: true, ...LIMITS });
});
afterEach(cleanup);

describe("overview narration section", () => {
  it("tells how long a script is when spoken and whether that is in range", async () => {
    workspace.metadata = { directory_path: "C:/p", overview_narration: "あ".repeat(1000), overview_narration_is_auto: false };
    await show();
    expect(await screen.findByText(/About 200 s spoken/)).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("Too long");
  });

  it("saves the project, runs overview-script and keeps the draft as an auto script", async () => {
    sidecar.callSidecar.mockResolvedValue({ success: true, script: "{start}案内{1}", source_ids: "a,b", model: null, ...LIMITS });
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Auto-write" }));
    await waitFor(() =>
      expect(workspace.updateMetadata).toHaveBeenCalledWith({
        overview_narration: "{start}案内{1}",
        overview_narration_is_auto: true,
        overview_narration_source_ids: "a,b",
      }),
    );
    expect(sidecar.callSidecar).toHaveBeenCalledWith(CONFIG, "overview-script");
    expect(workspace.saveProject.mock.invocationCallOrder[0]).toBeLessThan(sidecar.callSidecar.mock.invocationCallOrder[0]);
  });

  it("writes without AI through --no-llm", async () => {
    sidecar.callSidecar.mockResolvedValue({ success: true, script: "案内", source_ids: "a", model: null, ...LIMITS });
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Write without AI" }));
    await waitFor(() => expect(sidecar.callSidecar).toHaveBeenCalledWith(CONFIG, "overview-script --no-llm"));
  });

  it("asks before replacing a script the user wrote", async () => {
    workspace.metadata = { directory_path: "C:/p", overview_narration: "自分の案内", overview_narration_is_auto: false };
    sidecar.callSidecar.mockResolvedValue({ success: true, script: "新しい", source_ids: "a", model: null, ...LIMITS });
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Auto-write" }));
    expect(sidecar.callSidecar).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Replace" }));
    await waitFor(() => expect(sidecar.callSidecar).toHaveBeenCalledWith(CONFIG, "overview-script"));
  });

  it("marks a typed script as the user's own and keeps its cue buttons", async () => {
    await show();
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "手書き{1}" } });
    fireEvent.blur(screen.getByRole("textbox"));
    expect(workspace.updateMetadata).toHaveBeenCalledWith({
      overview_narration: "手書き{1}",
      overview_narration_is_auto: false,
      overview_narration_source_ids: undefined,
    });
    expect(screen.getByRole("button", { name: /overview stops at the next numbered stop/ }).textContent).toBe("{n}");
    expect(screen.getByRole("button", { name: /description of that stop ends/ }).textContent).toBe("{go}");
  });

  it("reverts to automatic only after confirming", async () => {
    workspace.metadata = { directory_path: "C:/p", overview_narration: "自分の案内", overview_narration_is_auto: false };
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Use automatic" }));
    expect(workspace.updateMetadata).not.toHaveBeenCalled();
    fireEvent.click(screen.getAllByRole("button", { name: "Use automatic" })[1]);
    expect(workspace.updateMetadata).toHaveBeenCalledWith(expect.objectContaining({ overview_narration: "", overview_narration_is_auto: true }));
  });
});
