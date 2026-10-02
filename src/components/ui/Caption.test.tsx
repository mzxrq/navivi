// @vitest-environment jsdom
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { Caption } from "./Caption";

afterEach(cleanup);

const box = (props: Parameters<typeof Caption>[0]) => render(<Caption {...props} />).getByText(props.text) as HTMLElement;

describe("Caption", () => {
  it("is a narrow box, so it stays clear of the card in the corner of a route clip", () => {
    expect(box({ text: "hi" }).style.maxWidth).toBe("50%");
  });

  it("sizes the text as a share of the frame height, 16 of 288 lines by default", () => {
    expect(parseFloat(box({ text: "hi" }).style.fontSize)).toBeCloseTo((16 / 288) * 100, 3);
    expect(parseFloat(box({ text: "bigger", size: 32 }).style.fontSize)).toBeCloseTo((32 / 288) * 100, 3);
  });

  it("draws the text and the box in the chosen colours, the box translucent by default", () => {
    const el = box({ text: "hi", color: "&H0000FFFF" });
    expect(el.style.color).toBe("rgb(255, 255, 0)");
    expect(el.style.backgroundColor).toBe("rgba(0, 0, 0, 0.6)");
  });

  it("falls back to the default font and bold off", () => {
    const el = box({ text: "hi" });
    expect(el.style.fontFamily).toContain("Yu Gothic UI");
    expect(el.style.fontWeight).toBe("400");
  });
});
