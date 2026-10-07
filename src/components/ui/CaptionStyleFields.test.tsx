// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../hooks/useInstalledFonts", () => ({
  BUILT_IN_FONTS: [],
  FONT_LANGUAGES: [],
  useInstalledFonts: () => ({ all: [], downloaded: [], language: {} }),
}));

import { DEFAULT_CAPTION_STYLE } from "../../utils/textStyle";
import { CaptionRow, CaptionStyleFields } from "./CaptionStyleFields";

i18n.load("en", {});
i18n.activate("en");
afterEach(cleanup);

const row: CaptionRow = (key, label, control) => (
  <div key={key} data-row={key}>
    <span>{label}</span>
    {control}
  </div>
);

const show = (kind: "caption" | "text" = "caption") => {
  const onChange = vi.fn();
  const view = render(
    <I18nProvider i18n={i18n}>
      <CaptionStyleFields style={DEFAULT_CAPTION_STYLE} onChange={onChange} row={row} kind={kind} />
    </I18nProvider>,
  );
  const input = (key: string) => view.container.querySelector<HTMLInputElement>(`[data-row="${key}"] input[type="number"]`)!;
  return { onChange, input, view };
};

describe("caption look extras", () => {
  it.each(["caption", "text"] as const)("%s style has shadow, letter spacing and opacity rows", (kind) => {
    const { input } = show(kind);
    expect(input("shadow")).toBeTruthy();
    expect(input("spacing")).toBeTruthy();
    expect(input("opacity")).toBeTruthy();
  });

  it("writes shadow distance and letter spacing as numbers, spacing may be negative", () => {
    const { input, onChange } = show();
    fireEvent.change(input("shadow"), { target: { value: "6" } });
    fireEvent.blur(input("shadow"));
    expect(onChange).toHaveBeenLastCalledWith({ shadow: 6 });
    fireEvent.change(input("spacing"), { target: { value: "-5" } });
    fireEvent.blur(input("spacing"));
    expect(onChange).toHaveBeenLastCalledWith({ letter_spacing: -5 });
  });

  it("shows opacity as a percent and writes it back as 0-1", () => {
    const { input, onChange } = show();
    expect(input("opacity").value).toBe("100");
    fireEvent.change(input("opacity"), { target: { value: "40" } });
    fireEvent.blur(input("opacity"));
    expect(onChange).toHaveBeenLastCalledWith({ opacity: 0.4 });
    expect(screen.getByLabelText("Shadow color")).toBeTruthy();
  });
});
