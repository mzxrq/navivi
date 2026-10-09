// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const ui = vi.hoisted(() => ({
  autoDirectorData: { state: "processing", content: "Kyoshi Sta. to Mt. Iimori", title: "Import document", fileName: "course.pdf" } as any,
  setAutoDirectorData: vi.fn(),
  showToast: vi.fn(),
}));
const workspace = vi.hoisted(() => ({ waypoints: [] as any[], setWaypoints: vi.fn(), updateSettings: vi.fn(), setIsDirty: vi.fn(), settings: {} as any }));
const built = vi.hoisted(() => ({ buildProject: vi.fn() }));
const geo = vi.hoisted(() => ({ searchPlaces: vi.fn() }));
vi.mock("../../hooks/useUI", () => ({ useUI: () => ui }));
vi.mock("../../hooks/useWorkspace", () => ({ useWorkspace: () => workspace }));
vi.mock("../../services/ai/engine", () => ({ aiEngine: () => "ollama" }));
vi.mock("../../services/assistant/buildProject", () => built);
vi.mock("../../services/geocode", async (original) => ({ ...(await original<typeof import("../../services/geocode")>()), ...geo }));

import { AutoDirectorModal } from "./AutoDirectorModal";

i18n.load("en", {});
i18n.activate("en");

const stop = (id: string, name: string, lat: number) => ({ id, name, lat, lng: 135.1, images: [], imagePans: [], routeMode: "walking", attractionNarration: `About ${name}` });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const renderModal = () =>
  render(
    <I18nProvider i18n={i18n}>
      <AutoDirectorModal />
    </I18nProvider>,
  );

describe("AutoDirectorModal", () => {
  it("is named after the import action and shows the file", async () => {
    built.buildProject.mockReturnValue(new Promise(() => {}));
    renderModal();
    expect(screen.getByRole("dialog", { name: "Import document" })).toBeTruthy();
    expect(screen.getByText("course.pdf")).toBeTruthy();
  });

  it("flags a guessed location, lets it be corrected, and adds the corrected stop", async () => {
    built.buildProject.mockResolvedValue({
      waypoints: [stop("a", "Kyoshi Sta.", 34.1), stop("b", "Mt. Iimori", 34.3)],
      failedPlaces: [],
      uncertainPlaces: ["Kyoshi Sta."],
      uncertain: [true, false],
    });
    renderModal();
    await screen.findByText("Check location");

    const coords = screen.getByPlaceholderText("34.2908, 135.1508") as HTMLInputElement;
    fireEvent.change(coords, { target: { value: "34.2908, 135.1508" } });
    fireEvent.blur(coords);
    await waitFor(() => expect(screen.queryByText("Check location")).toBeNull(), { timeout: 4000 });

    fireEvent.click(screen.getByRole("button", { name: "Create 2 stops" }));
    const applied = workspace.setWaypoints.mock.calls[0][0];
    expect(applied[0]).toMatchObject({ name: "Kyoshi Sta.", lat: 34.2908, lng: 135.1508 });
    expect(applied[1]).toMatchObject({ name: "Mt. Iimori", lat: 34.3 });
  });

  it("takes a searched place and can leave a stop out", async () => {
    built.buildProject.mockResolvedValue({
      waypoints: [stop("a", "Kosen-ji Temple", 33.7), stop("b", "Mt. Takano", 33.8)],
      failedPlaces: [],
      uncertainPlaces: [],
      uncertain: [true, false],
    });
    geo.searchPlaces.mockResolvedValue([{ name: "Kosen-ji, Misaki, Osaka", lat: 34.279, lng: 135.166 }]);
    renderModal();
    await screen.findByText("Check location");

    fireEvent.change(screen.getByPlaceholderText("Search for the right place"), { target: { value: "Kosen-ji Misaki" } });
    fireEvent.click(screen.getByRole("button", { name: /Search/ }));
    fireEvent.click(await screen.findByText("Kosen-ji, Misaki, Osaka"));
    await waitFor(() => expect(screen.queryByText("Check location")).toBeNull(), { timeout: 4000 });

    fireEvent.click(screen.getAllByRole("button", { name: "Leave this stop out" })[1]);
    fireEvent.click(screen.getByRole("button", { name: "Create 1 stops" }));
    expect(workspace.setWaypoints.mock.calls[0][0]).toEqual([expect.objectContaining({ name: "Kosen-ji Temple", lat: 34.279, lng: 135.166 })]);
  });

  it("offers the document's course introduction and saves it as the overview introduction", async () => {
    built.buildProject.mockResolvedValue({
      waypoints: [stop("a", "Kyoshi Sta.", 34.29), stop("b", "Mt. Iimori", 34.3)],
      failedPlaces: [],
      uncertainPlaces: [],
      uncertain: [false, false],
      overviewIntro: "A 10 km walk past old ascetic sites.",
    });
    renderModal();
    const box = (await screen.findByDisplayValue("A 10 km walk past old ascetic sites.")) as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "A walk through the hills." } });
    fireEvent.click(screen.getByRole("button", { name: "Create 2 stops" }));
    expect(workspace.updateSettings).toHaveBeenCalledWith({ overview_intro: "A walk through the hills.", overview_style: "course" });
  });

  it("marks a confidently matched stop that is far from the rest of the route", async () => {
    const at = (id: string, name: string, lat: number, lng: number) => ({ ...stop(id, name, lat), lng });
    built.buildProject.mockResolvedValue({
      waypoints: [at("a", "Kyoshi Sta.", 34.29, 135.15), at("b", "Mt. Iimori", 34.3, 135.18), at("c", "Mt. Fudatate", 34.286, 135.191), at("d", "Kosen-ji Temple", 33.73, 135.38)],
      failedPlaces: [],
      uncertainPlaces: [],
      uncertain: [false, false, false, false],
    });
    renderModal();
    expect(await screen.findAllByText("Check location")).toHaveLength(1);
    expect(screen.getByText(/Check the 1 marked locations/)).toBeTruthy();
  });

  it("keeps a failure inside the window", async () => {
    built.buildProject.mockResolvedValue({ waypoints: [], failedPlaces: ["Nowhere"], uncertainPlaces: [], uncertain: [] });
    renderModal();
    expect(await screen.findByText(/No places could be located/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Close" }).length).toBeGreaterThan(0);
  });
});
