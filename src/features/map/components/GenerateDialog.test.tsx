// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const workspace = vi.hoisted(() => ({
  waypoints: [] as unknown[],
  settings: {} as Record<string, unknown>,
  metadata: { directory_path: "C:/p", project_name: "P" },
  updateSettings: vi.fn(),
  setIsDirty: vi.fn(),
  saveProject: vi.fn(async () => {}),
}));
vi.mock("../../../hooks/useWorkspace", () => ({ useWorkspace: () => workspace }));
vi.mock("../../../services/renderEstimate", () => ({ fetchRenderEstimate: async () => null, formatDuration: () => "", }));
vi.mock("../../../services/assetCleanup", async (orig) => ({
  ...(await orig<typeof import("../../../services/assetCleanup")>()),
  scanAssets: async () => ({ voice: 3, subtitles: 3, route: 2, photo: 0, cards: 1 }),
}));

import { GenerateDialog } from "./GenerateDialog";

i18n.load("en", {});
i18n.activate("en");

const show = (onConfirm = vi.fn()) => {
  render(
    <I18nProvider i18n={i18n}>
      <GenerateDialog onClose={() => {}} onConfirm={onConfirm} />
    </I18nProvider>,
  );
  return onConfirm;
};

afterEach(cleanup);

describe("GenerateDialog: make everything again", () => {
  it("generates as before when the option is left off", async () => {
    const onConfirm = show();
    await screen.findByText("This project already has assets");
    fireEvent.click(screen.getByRole("button", { name: "Generate assets" }));
    expect(onConfirm).toHaveBeenCalledWith([], false);
  });

  it("includes every group, locks the ticks and asks once more before sending force", async () => {
    const onConfirm = show();
    await screen.findByText("This project already has assets");
    fireEvent.click(screen.getByRole("switch", { name: "Make everything again" }));
    expect((screen.getByRole("checkbox", { name: "Voiceover" }) as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole("checkbox", { name: "Voiceover" }) as HTMLInputElement).checked).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Make everything again" }));
    expect(onConfirm).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Yes, make everything again" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith([], true));
  });
});
