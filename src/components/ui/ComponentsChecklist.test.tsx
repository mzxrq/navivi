// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sidecar = vi.hoisted(() => ({ callSidecar: vi.fn(), callSidecarShared: vi.fn() }));
const ollama = vi.hoisted(() => ({ getOllamaState: vi.fn() }));
const setup = vi.hoisted(() => ({ installVcRuntime: vi.fn() }));
const online = vi.hoisted(() => ({ hasApiKey: vi.fn() }));
vi.mock("../../services/sidecar", () => sidecar);
vi.mock("../../services/ollamaApi", () => ollama);
vi.mock("../../services/ai/online", () => online);
vi.mock("../../services/setup", () => setup);
vi.mock("../../hooks/useWorkspace", () => ({ useWorkspace: () => ({ settings: { ai_features_enabled: true }, updateSettings: vi.fn(), setIsDirty: vi.fn() }) }));
vi.mock("./OnlineAiSettings", () => ({ ProviderPicker: ({ children }: { children?: React.ReactNode }) => <>{children}</>, OnlineProviderSettings: () => null }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(() => Promise.resolve(() => {})) }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(() => Promise.resolve()) }));

import { getInstalls, resetInstalls } from "../../services/installs";
import { ComponentsChecklist } from "./ComponentsChecklist";

i18n.load("en", {});
i18n.activate("en");

const engines = (ready: Partial<Record<"irodori" | "qwen3" | "kokoro" | "comfyui", boolean>>, nvidia = false) => ({
  success: true,
  irodori: { ready: !!ready.irodori },
  qwen3: { ready: !!ready.qwen3 },
  kokoro: { ready: !!ready.kokoro },
  comfyui: { ready: !!ready.comfyui, nvidia },
  vc_runtime: true,
});

const down = { running: false, models: [] as string[] };

const show = () =>
  render(
    <I18nProvider i18n={i18n}>
      <ComponentsChecklist />
    </I18nProvider>,
  );

beforeEach(() => {
  ollama.getOllamaState.mockResolvedValue(down);
  setup.installVcRuntime.mockResolvedValue(undefined);
  online.hasApiKey.mockResolvedValue(false);
  sidecar.callSidecarShared.mockResolvedValue(engines({}));
  sidecar.callSidecar.mockResolvedValue({ success: true });
});
afterEach(() => {
  cleanup();
  resetInstalls();
});

describe("ComponentsChecklist", () => {
  it("offers a Set up button for each voice that is missing and none for one that is ready", async () => {
    sidecar.callSidecarShared.mockResolvedValue(engines({ kokoro: true }));
    show();
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Set up" })).toHaveLength(2));
    expect(screen.getAllByText("Ready")).toHaveLength(1);
  });

  it("sets a voice up with its own action and then asks again what is ready", async () => {
    show();
    const buttons = await waitFor(() => {
      const found = screen.getAllByRole("button", { name: "Set up" });
      expect(found).toHaveLength(3);
      return found;
    });
    sidecar.callSidecarShared.mockResolvedValue(engines({ kokoro: true }));
    fireEvent.click(buttons[0]); // the fast voice is listed first
    await waitFor(() => expect(sidecar.callSidecar).toHaveBeenCalledWith("tts_install_kokoro", {}));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Set up" })).toHaveLength(2));
  });

  it("does not start a second install while one runs, which would cancel it, and shows its progress", async () => {
    let finish: (v: unknown) => void = () => {};
    sidecar.callSidecar.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    show();
    const buttons = await waitFor(() => screen.getAllByRole("button", { name: "Set up" }));
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(screen.getByText("0%")).toBeTruthy());
    for (const button of screen.getAllByRole("button", { name: "Set up" })) expect((button as HTMLButtonElement).disabled).toBe(true);
    finish({ success: true });
    await waitFor(() => expect(screen.queryByText("0%")).toBeNull());
    await waitFor(() => expect((screen.getAllByRole("button", { name: "Set up" })[0] as HTMLButtonElement).disabled).toBe(false));
  });

  it("keeps a failed install's message for the details window", async () => {
    sidecar.callSidecar.mockResolvedValue({ success: false, error: "uv is missing" });
    show();
    const buttons = await waitFor(() => screen.getAllByRole("button", { name: "Set up" }));
    fireEvent.click(buttons[1]);
    await waitFor(() => expect(getInstalls()[0]?.state).toBe("failed"));
    expect(getInstalls()[0].error).toBe("uv is missing");
  });

  it("says Ollama is ready when it has models", async () => {
    ollama.getOllamaState.mockResolvedValue({ running: true, models: ["gemma"] });
    show();
    await waitFor(() => expect(screen.getAllByText("Ready")).toHaveLength(1));
    expect(screen.getByText(/Running, with 1 model/)).toBeTruthy();
  });

  it("offers to install Ollama when it is not found, and asks before running the installer", async () => {
    show();
    const install = await waitFor(() => screen.getByRole("button", { name: "Install now" }));
    expect(screen.getByRole("button", { name: /Get Ollama/ })).toBeTruthy();
    fireEvent.click(install);
    expect(sidecar.callSidecar).not.toHaveBeenCalledWith("ollama_install", {});
    expect(screen.getByText("irm https://ollama.com/install.ps1 | iex")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    await waitFor(() => expect(sidecar.callSidecar).toHaveBeenCalledWith("ollama_install", {}));
  });

  it("notices Ollama appearing after the first look", async () => {
    show();
    await waitFor(() => expect(screen.getByRole("button", { name: "Install now" })).toBeTruthy());
    ollama.getOllamaState.mockResolvedValue({ running: true, models: ["gemma"] });
    window.dispatchEvent(new Event("focus"));
    await waitFor(() => expect(screen.getByText(/Running, with 1 model/)).toBeTruthy());
  });

  it("offers the Visual C++ runtime only when it is missing", async () => {
    show();
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Set up" })).toHaveLength(3));
    expect(screen.queryByText("Microsoft Visual C++ runtime")).toBeNull();
    cleanup();
    sidecar.callSidecarShared.mockResolvedValue({ ...engines({}), vc_runtime: false });
    show();
    await waitFor(() => expect(screen.getByText("Microsoft Visual C++ runtime")).toBeTruthy());
    fireEvent.click(screen.getAllByRole("button", { name: "Install now" })[0]);
    await waitFor(() => expect(setup.installVcRuntime).toHaveBeenCalled());
  });

  it("names the model behind each voice so it can be credited", async () => {
    show();
    await waitFor(() => expect(screen.getByText("Kokoro-82M")).toBeTruthy());
    expect(screen.getByText("Qwen3-TTS")).toBeTruthy();
    expect(screen.getByText("Irodori-TTS")).toBeTruthy();
    expect(screen.getByText(/By hexgrad, Apache-2.0/)).toBeTruthy();
  });

  it("offers the moving attraction videos with its own install action when an NVIDIA card is there", async () => {
    sidecar.callSidecarShared.mockResolvedValue(engines({}, true));
    show();
    const buttons = await waitFor(() => {
      const found = screen.getAllByRole("button", { name: "Set up" });
      expect(found).toHaveLength(4);
      return found;
    });
    sidecar.callSidecar.mockReturnValue(new Promise(() => {}));
    fireEvent.click(buttons[3]);
    await waitFor(() => expect(sidecar.callSidecar).toHaveBeenCalledWith("comfyui_install", {}));
    await waitFor(() => expect(screen.getByText(/Installing in the background/)).toBeTruthy());
  });

  it("does not offer the download without an NVIDIA card and says why", async () => {
    show();
    await waitFor(() => expect(screen.getByText("Needs an NVIDIA graphics card")).toBeTruthy());
    expect(screen.getAllByRole("button", { name: "Set up" })).toHaveLength(3);
    expect(screen.getByText("Moving attraction videos").closest("[aria-disabled]")?.getAttribute("aria-disabled")).toBe("true");
  });

  it("tells the user what is still missing, and when nothing is", async () => {
    show();
    await waitFor(() => expect(screen.getByText(/Set up at least one voice/)).toBeTruthy());
    expect(screen.getByText("Optional")).toBeTruthy();
    cleanup();
    sidecar.callSidecarShared.mockResolvedValue(engines({ kokoro: true, comfyui: true }, true));
    ollama.getOllamaState.mockResolvedValue({ running: true, models: ["gemma4:26b"] });
    show();
    await waitFor(() => expect(screen.getByText("Everything you need is set up.")).toBeTruthy());
  });
});
