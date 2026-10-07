// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sidecar = vi.hoisted(() => ({ callSidecar: vi.fn(), callSidecarShared: vi.fn() }));
const workspace = vi.hoisted(() => ({ settings: {} as Record<string, unknown>, updateSettings: vi.fn(), setIsDirty: vi.fn() }));
vi.mock("../../services/sidecar", () => sidecar);
vi.mock("../../hooks/useWorkspace", () => ({ useWorkspace: () => workspace }));
vi.mock("@tauri-apps/api/core", () => ({ convertFileSrc: (p: string) => p }));
vi.mock("@tauri-apps/plugin-dialog", () => ({ open: vi.fn() }));

import { VoiceTab } from "./VoiceSettings";
import { DEFAULT_TTS_CAPTION, formatBytes } from "./voiceOptions";

i18n.load("en", {});
i18n.activate("en");

const MB = 1024 * 1024;
let cacheFiles = 3;

const show = () =>
  render(
    <I18nProvider i18n={i18n}>
      <VoiceTab />
    </I18nProvider>,
  );

beforeEach(() => {
  cacheFiles = 3;
  workspace.settings = {};
  workspace.updateSettings.mockReset();
  workspace.setIsDirty.mockReset();
  sidecar.callSidecar.mockReset();
  sidecar.callSidecarShared.mockImplementation(async (action: string) => {
    if (action === "tts_voices_list") return { success: true, voices: [] };
    if (action === "tts_engines")
      return { success: true, kokoro: { ready: false, default_voice: "x", voices: [] }, qwen3: { ready: true }, irodori: { ready: true } };
    if (action === "tts_cache_info") return { success: true, files: cacheFiles, bytes: 120 * MB, max_bytes: 500 * MB };
    return { success: false, error: action };
  });
  sidecar.callSidecar.mockImplementation(async (action: string) => {
    if (action === "tts_cache_clear") {
      cacheFiles = 0;
      return { success: true, files: 3, bytes: 120 * MB };
    }
    if (action === "tts_cache_info") return { success: true, files: cacheFiles, bytes: 0, max_bytes: 500 * MB };
    return { success: true };
  });
});
afterEach(cleanup);

describe("formatBytes", () => {
  it("picks a readable unit", () => {
    expect(formatBytes(0)).toBe("0 KB");
    expect(formatBytes(512 * 1024)).toBe("512 KB");
    expect(formatBytes(5.5 * MB)).toBe("5.5 MB");
    expect(formatBytes(500 * MB)).toBe("500 MB");
    expect(formatBytes(2048 * MB)).toBe("2.0 GB");
  });
});

describe("Voice tab speed", () => {
  it("reaches the engine's whole 0.25-4x range", async () => {
    show();
    const slider = (await screen.findByLabelText("Narration speed")) as HTMLInputElement;
    expect([slider.min, slider.max]).toEqual(["0.25", "4"]);
  });
});

describe("Voice tab speaking style", () => {
  it("shows the default style, and a preset saves it, dropping the key for the default one", async () => {
    show();
    const box = (await screen.findByLabelText("Speaking style")) as HTMLInputElement;
    expect(box.value).toBe(DEFAULT_TTS_CAPTION);
    fireEvent.click(screen.getByRole("button", { name: "Calm" }));
    expect(workspace.updateSettings).toHaveBeenCalledWith({ tts: { caption: "落ち着いた、穏やかな話し方。" } });
    expect(workspace.setIsDirty).toHaveBeenCalledWith(true);
  });

  it("an empty box saves an empty style (no style), and Reset drops the key", async () => {
    workspace.settings = { tts: { caption: "落ち着いた、穏やかな話し方。" } };
    show();
    const box = (await screen.findByLabelText("Speaking style")) as HTMLInputElement;
    fireEvent.change(box, { target: { value: "" } });
    fireEvent.blur(box);
    expect(workspace.updateSettings).toHaveBeenLastCalledWith({ tts: { caption: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Reset speaking style" }));
    expect(workspace.updateSettings).toHaveBeenLastCalledWith({ tts: { caption: undefined } });
  });

  it("does not save when the text did not change", async () => {
    show();
    const box = (await screen.findByLabelText("Speaking style")) as HTMLInputElement;
    fireEvent.change(box, { target: { value: DEFAULT_TTS_CAPTION } });
    fireEvent.blur(box);
    expect(workspace.updateSettings).not.toHaveBeenCalled();
  });

  it("is only offered for the natural voice", async () => {
    workspace.settings = { tts: { engine: "qwen3" } };
    show();
    await screen.findByText("Voice cache");
    expect(screen.queryByLabelText("Speaking style")).toBeNull();
  });
});

describe("Voice tab timing cues", () => {
  it("both switches start on and write their own setting", async () => {
    show();
    const overview = await screen.findByRole("switch", { name: "Place cues in the overview narration" });
    expect(overview.getAttribute("aria-checked")).toBe("true");
    fireEvent.click(overview);
    expect(workspace.updateSettings).toHaveBeenCalledWith({ auto_overview_cues: false });
    fireEvent.click(screen.getByRole("switch", { name: "Place cues in each stop's narration" }));
    expect(workspace.updateSettings).toHaveBeenLastCalledWith({ auto_narration_cues: false });
  });
});

describe("Voice tab cache", () => {
  it("shows the size, asks before clearing, then shows the emptied cache", async () => {
    show();
    expect(await screen.findByText("120 MB of 500 MB")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Clear cache" }));
    expect(sidecar.callSidecar).not.toHaveBeenCalledWith("tts_cache_clear", expect.anything());
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(sidecar.callSidecar).toHaveBeenCalledWith("tts_cache_clear", {}));
    await waitFor(() => expect(screen.getByRole("button", { name: "Clear cache" }).hasAttribute("disabled")).toBe(true));
  });
});
