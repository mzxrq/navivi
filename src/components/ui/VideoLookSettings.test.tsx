// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ProjectSettings } from "../../types";
import { VideoLookSettings } from "./VideoLookSettings";

i18n.load("en", {});
i18n.activate("en");
afterEach(cleanup);

const show = (options: Partial<ProjectSettings> = {}) => {
  const onChange = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <VideoLookSettings options={options} onChange={onChange} />
    </I18nProvider>,
  );
  return onChange;
};

describe("VideoLookSettings", () => {
  it("shows the renderer's defaults for a project that sets nothing", () => {
    show();
    expect(screen.getByRole("switch", { name: "Add an outro" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("switch", { name: "Compass on stop maps" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("switch", { name: "Wide view before each leg" }).getAttribute("aria-checked")).toBe("false");
    expect(screen.getByRole("button", { name: "Columns" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "Dark" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("writes only the key that changed", () => {
    const onChange = show();
    fireEvent.click(screen.getByRole("switch", { name: "Add an outro" }));
    expect(onChange).toHaveBeenCalledWith({ enable_outro: false });
    fireEvent.click(screen.getByRole("button", { name: "Taskbar" }));
    expect(onChange).toHaveBeenCalledWith({ summary_card_style: "taskbar" });
  });

  it("hides the outro style and facts while the outro is off", () => {
    show({ enable_outro: false });
    expect(screen.queryByRole("button", { name: "Grid" })).toBeNull();
  });

  it("resets a color by removing its key", () => {
    const onChange = show({ start_pin_color: [1, 2, 3] });
    fireEvent.click(screen.getAllByRole("button", { name: "Reset" }).find((b) => !(b as HTMLButtonElement).disabled)!);
    expect(onChange).toHaveBeenCalledWith({ start_pin_color: undefined });
  });

  it("removes the mode colors object once the last mode is reset", () => {
    const onChange = show({ mode_line_colors: { ferry: [1, 2, 3] } });
    fireEvent.click(screen.getAllByRole("button", { name: "Reset" }).find((b) => !(b as HTMLButtonElement).disabled)!);
    expect(onChange).toHaveBeenCalledWith({ mode_line_colors: undefined });
  });
});
