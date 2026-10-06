// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sidecar = vi.hoisted(() => ({ callSidecar: vi.fn(), callSidecarShared: vi.fn() }));
const ollama = vi.hoisted(() => ({ getLocalModels: vi.fn() }));
const online = vi.hoisted(() => ({ hasApiKey: vi.fn() }));
vi.mock("../../services/sidecar", () => sidecar);
vi.mock("../../services/ollamaApi", () => ollama);
vi.mock("../../services/ai/online", () => online);
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn(() => Promise.resolve()) }));

import { ComponentsChecklist } from "./ComponentsChecklist";

i18n.load("en", {});
i18n.activate("en");

const engines = (ready: Partial<Record<"irodori" | "qwen3" | "kokoro" | "comfyui", boolean>>, nvidia = false) => ({
  success: true,
  irodori: { ready: !!ready.irodori },
  qwen3: { ready: !!ready.qwen3 },
  kokoro: { ready: !!ready.kokoro },
  comfyui: { ready: !!ready.comfyui, nvidia },
});

const show = () =>
  render(
    <I18nProvider i18n={i18n}>
      <ComponentsChecklist />
    </I18nProvider>,
  );

beforeEach(() => {
  ollama.getLocalModels.mockResolvedValue([]);
  online.hasApiKey.mockResolvedValue(false);
  sidecar.callSidecarShared.mockResolvedValue(engines({}));
  sidecar.callSidecar.mockResolvedValue({ success: true });
});
afterEach(cleanup);

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

  it("does not start a second install while one runs, which would cancel it", async () => {
    let finish: (v: unknown) => void = () => {};
    sidecar.callSidecar.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    show();
    const buttons = await waitFor(() => screen.getAllByRole("button", { name: "Set up" }));
    fireEvent.click(buttons[0]);
    await waitFor(() => expect(screen.getByRole("button", { name: /Setting up/ })).toBeTruthy());
    for (const button of screen.getAllByRole("button", { name: "Set up" })) expect((button as HTMLButtonElement).disabled).toBe(true);
    finish({ success: true });
    await waitFor(() => expect(screen.queryByRole("button", { name: /Setting up/ })).toBeNull());
  });

  it("shows a failed install's message", async () => {
    sidecar.callSidecar.mockResolvedValue({ success: false, error: "uv is missing" });
    show();
    const buttons = await waitFor(() => screen.getAllByRole("button", { name: "Set up" }));
    fireEvent.click(buttons[1]);
    await waitFor(() => expect(screen.getByText("uv is missing")).toBeTruthy());
  });

  it("says Ollama is ready when it has models and a provider is ready when its key is saved", async () => {
    ollama.getLocalModels.mockResolvedValue(["gemma"]);
    online.hasApiKey.mockImplementation(async (provider: string) => provider === "anthropic");
    show();
    await waitFor(() => expect(screen.getAllByText("Ready")).toHaveLength(2));
    expect(screen.getByText(/Key saved for Anthropic/)).toBeTruthy();
  });

  it("points to the Ollama download page when it is not found", async () => {
    show();
    await waitFor(() => expect(screen.getByRole("button", { name: /Get Ollama/ })).toBeTruthy());
  });

  it("names the model behind each voice so it can be credited", async () => {
    show();
    await waitFor(() => expect(screen.getByText("Fast voice · Kokoro-82M")).toBeTruthy());
    expect(screen.getByText("Balanced voice · Qwen3-TTS")).toBeTruthy();
    expect(screen.getByText("Natural voice · Irodori-TTS")).toBeTruthy();
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
    await waitFor(() => expect(screen.getByText(/about 30 GB and can take an hour/)).toBeTruthy());
  });

  it("does not offer the download without an NVIDIA card and says why", async () => {
    show();
    await waitFor(() => expect(screen.getByText("Needs an NVIDIA graphics card")).toBeTruthy());
    expect(screen.getAllByRole("button", { name: "Set up" })).toHaveLength(3);
  });

  it("tells the user what is still missing, and when nothing is", async () => {
    show();
    await waitFor(() => expect(screen.getByText(/Set up at least one voice/)).toBeTruthy());
    expect(screen.getByText(/Optional: a script writer/)).toBeTruthy();
    cleanup();
    sidecar.callSidecarShared.mockResolvedValue(engines({ kokoro: true, comfyui: true }, true));
    ollama.getLocalModels.mockResolvedValue(["gemma4:26b"]);
    show();
    await waitFor(() => expect(screen.getByText("Everything you need is set up.")).toBeTruthy());
  });
});
