// @vitest-environment jsdom
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Slider } from "./Slider";

afterEach(cleanup);

const setup = (props: Partial<Parameters<typeof Slider>[0]> = {}) => {
  const view = render(<Slider label="Volume" value={0.5} min={0} max={1} step={0.05} {...props} />);
  const input = view.getByLabelText("Volume") as HTMLInputElement;
  const thumb = () => view.container.querySelector<HTMLElement>("span.h-4.w-1")!;
  return { ...view, input, thumb };
};

describe("Slider", () => {
  it("is a real range input, so keyboard and screen readers work", () => {
    const { input } = setup();
    expect(input.type).toBe("range");
    expect([input.min, input.max, input.step, input.value]).toEqual(["0", "1", "0.05", "0.5"]);
  });

  it("reports every move as a number", () => {
    const onChange = vi.fn();
    const { input } = setup({ onChange });
    fireEvent.change(input, { target: { value: "0.8" } });
    expect(onChange).toHaveBeenCalledWith(0.8);
  });

  it("commits once when the drag ends on a different value, and not when nothing changed", () => {
    const onCommit = vi.fn();
    const { input } = setup({ onCommit });
    fireEvent.pointerUp(input);
    expect(onCommit).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "0.8" } });
    expect(onCommit).not.toHaveBeenCalled();
    fireEvent.pointerUp(input);
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith(0.8);
  });

  it("commits a keyboard change on key up", () => {
    const onCommit = vi.fn();
    const { input } = setup({ onCommit });
    fireEvent.change(input, { target: { value: "0.55" } });
    fireEvent.keyUp(input);
    expect(onCommit).toHaveBeenCalledWith(0.55);
  });

  it("follows the value it is given from outside", () => {
    const { input, rerender } = setup();
    rerender(<Slider label="Volume" value={0.9} min={0} max={1} step={0.05} />);
    expect(input.value).toBe("0.9");
  });

  it("draws one tick per step, and thins them out for a fine range", () => {
    const ticks = (c: HTMLElement) => c.querySelectorAll("span.w-px").length;
    expect(ticks(setup().container)).toBe(21); // 0..1 by 0.05
    cleanup();
    expect(ticks(setup({ min: 0, max: 1000, step: 1 }).container)).toBe(21); // too many steps: every 5%
  });

  it("puts the handle at the value's share of the range, leaving room for its own width", () => {
    const share = (value: number) => {
      const left = setup({ value }).thumb().style.left;
      cleanup();
      return left;
    };
    expect(share(0)).toContain("0 * (100% - 4px)");
    expect(share(1)).toContain("1 * (100% - 4px)");
    expect(share(0.25)).toContain("0.25 * (100% - 4px)");
  });

  it("shows the formatted value in the tag", () => {
    const { getByText } = setup({ value: 0.6, format: (v) => `${Math.round(v * 100)}%` });
    expect(getByText("60%")).toBeTruthy();
  });

  it("cannot be moved when disabled", () => {
    expect(setup({ disabled: true }).input.disabled).toBe(true);
  });
});
