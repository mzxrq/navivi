// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DrawBar } from "../../../../src/features/map/components/DrawBar";

i18n.load("en", {});
i18n.activate("en");

const wp = (id: string, name: string, extra: object = {}) => ({ id, name, lat: 35, lng: 135, images: [], imagePans: [], routeMode: "draw", ...extra }) as any;

afterEach(cleanup);

function setup() {
  const a = wp("a", "Start", { customRoute: [[35.1, 135.1], [35.2, 135.2]] });
  const b = wp("b", "End");
  const updateWaypoint = vi.fn();
  const setIsDirty = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <DrawBar
        waypoints={[a, b]}
        activeWp={a}
        nextWp={b}
        isEraserMode={false}
        setIsEraserMode={() => {}}
        onPickLeg={() => {}}
        onFit={() => {}}
        onDone={() => {}}
        updateWaypoint={updateWaypoint}
        setIsDirty={setIsDirty}
      />
    </I18nProvider>,
  );
  fireEvent.click(screen.getByTitle("Show the list of points"));
  return { updateWaypoint, setIsDirty };
}

describe("DrawBar point coordinates", () => {
  it("types new coordinates into a point by double-clicking it", () => {
    const { updateWaypoint, setIsDirty } = setup();
    fireEvent.doubleClick(screen.getByText("35.20000, 135.20000"));
    const input = screen.getByLabelText("Coordinates of point 2") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "34.2908, 135.1508" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(updateWaypoint).toHaveBeenCalledWith("a", { customRoute: [[35.1, 135.1], [34.2908, 135.1508]] });
    expect(setIsDirty).toHaveBeenCalledWith(true);
  });

  it("keeps the point when the entry is not a coordinate pair", () => {
    const { updateWaypoint } = setup();
    fireEvent.doubleClick(screen.getByText("35.10000, 135.10000"));
    const input = screen.getByLabelText("Coordinates of point 1");
    fireEvent.change(input, { target: { value: "somewhere" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(input.getAttribute("aria-invalid")).toBe("true");
    fireEvent.blur(input);
    expect(updateWaypoint).not.toHaveBeenCalled();
    expect(screen.getByText("35.10000, 135.10000")).toBeTruthy();
  });

  it("curves only the point whose curve button is pressed", () => {
    const { updateWaypoint } = setup();
    fireEvent.click(screen.getAllByLabelText("Make this smooth")[1]);
    expect(updateWaypoint).toHaveBeenCalledWith("a", { customRoute: [[35.1, 135.1], [35.2, 135.2]], customRouteCurve: [null, "auto"], drawStyle: undefined });
  });

  it("smooths every point at once and straightens them on the second press", () => {
    const { updateWaypoint } = setup();
    fireEvent.click(screen.getByTitle("Make every point smooth, or every point a corner"));
    expect(updateWaypoint).toHaveBeenCalledWith("a", { customRoute: [[35.1, 135.1], [35.2, 135.2]], customRouteCurve: ["auto", "auto"], drawStyle: undefined });
  });
});
