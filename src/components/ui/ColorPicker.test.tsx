// @vitest-environment jsdom
import { i18n } from "@lingui/core";
import { I18nProvider } from "@lingui/react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ColorPicker } from "./ColorPicker";

i18n.load("en", {});
i18n.activate("en");

afterEach(cleanup);
beforeEach(() => localStorage.clear());

function Harness({ onChange }: { onChange: (hex: string) => void }) {
  const [value, setValue] = useState("#FFFFFF");
  return (
    <I18nProvider i18n={i18n}>
      <ColorPicker
        label="Text colour"
        value={value}
        onChange={(hex) => {
          setValue(hex);
          onChange(hex);
        }}
      />
    </I18nProvider>
  );
}

const open = () => fireEvent.click(screen.getByRole("button", { name: "Text colour" }));

describe("ColorPicker", () => {
  it("shows the current colour on its button and opens a dialog with the controls", () => {
    render(<Harness onChange={() => {}} />);
    expect(screen.getByRole("button", { name: "Text colour" }).textContent).toContain("#FFFFFF");
    open();
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByRole("slider", { name: "Hue" })).toBeTruthy();
    expect(screen.getByRole("textbox", { name: "Hex colour" })).toBeTruthy();
  });

  it("picks a preset with one click", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "#EF4444" }));
    expect(onChange).toHaveBeenCalledWith("#EF4444");
    expect(screen.getByRole("button", { name: "Text colour" }).textContent).toContain("#EF4444");
  });

  it("takes a typed hex on Enter, in short form too, and ignores a bad one", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    open();
    const hex = screen.getByRole("textbox", { name: "Hex colour" });
    fireEvent.change(hex, { target: { value: "#0af" } });
    fireEvent.keyDown(hex, { key: "Enter" });
    expect(onChange).toHaveBeenLastCalledWith("#00AAFF");
    fireEvent.change(hex, { target: { value: "#12" } });
    fireEvent.keyDown(hex, { key: "Enter" });
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("moves the colour with the arrow keys on the square and the hue bar", () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    open();
    fireEvent.keyDown(screen.getByRole("slider", { name: "Saturation and brightness" }), { key: "ArrowDown", shiftKey: true });
    expect(onChange).toHaveBeenLastCalledWith("#E6E6E6"); // white, 10% darker
    fireEvent.keyDown(screen.getByRole("slider", { name: "Hue" }), { key: "ArrowRight" });
    expect(onChange).toHaveBeenCalledTimes(1); // a grey has no hue to move
    fireEvent.click(screen.getByRole("button", { name: "#EF4444" }));
    fireEvent.keyDown(screen.getByRole("slider", { name: "Hue" }), { key: "ArrowRight", shiftKey: true });
    expect(onChange).toHaveBeenCalledTimes(3);
    expect(onChange).toHaveBeenLastCalledWith(expect.not.stringMatching(/^#EF4444$/));
  });

  it("remembers the colours you picked and offers them as recent", () => {
    render(<Harness onChange={() => {}} />);
    open();
    fireEvent.click(screen.getByRole("button", { name: "#8B5CF6" }));
    cleanup();
    render(<Harness onChange={() => {}} />);
    open();
    expect(screen.getByText("Recent")).toBeTruthy();
    expect(JSON.parse(localStorage.getItem("navivi.recentColors") ?? "[]")).toEqual(["#8B5CF6"]);
  });

  it("closes on Escape", () => {
    render(<Harness onChange={() => {}} />);
    open();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
