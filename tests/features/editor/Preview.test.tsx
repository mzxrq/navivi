// @vitest-environment jsdom
import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);
import { ShiftedLayer, TextBoxBand } from "../../../src/features/editor/Preview";
import { player } from "../../../src/features/editor/player";
import type { PlacedText } from "../../../src/features/editor/model";

const text = (over: Partial<PlacedText>): PlacedText =>
  ({ id: "t", segmentId: "o", start: 0, end: 5, globalStart: 0, globalEnd: 5, kind: "outro", title: { text: "T" }, subtitle: { text: "" }, ...over }) as PlacedText;
const cq = (px: number) => `${px}%`; // jsdom does not know cqh

describe("TextBoxBand", () => {
  it("draws a top box from the top edge with a soft edge under it", () => {
    const item = text({ position: "top", box: { color: "#FF0000", opacity: 0.5, height: 200, fade: 40 } });
    const { container } = render(<TextBoxBand item={item} cq={cq} />);
    const [band, edge] = Array.from(container.querySelectorAll("div")) as HTMLElement[];
    expect(band.style.height).toBe("200%");
    expect(band.style.top).toBe("0px");
    expect(band.style.background).toContain("rgba(255, 0, 0, 0.5)");
    expect(edge.style.top).toBe("200%");
    expect(edge.style.height).toBe("40%");
    expect(edge.style.background).toContain("linear-gradient");
  });

  it("has no soft edge for a middle box, and nothing without a box", () => {
    const middle = render(<TextBoxBand item={text({ box: { color: "#000000", opacity: 1, height: 100, fade: 40 } })} cq={cq} />);
    expect(middle.container.querySelectorAll("div")).toHaveLength(1);
    const none = render(<TextBoxBand item={text({})} cq={cq} />);
    expect(none.container.querySelectorAll("div")).toHaveLength(0);
  });
});

describe("ShiftedLayer", () => {
  it("moves the video down while the outro's box is taller than the video was drawn for", () => {
    const item = text({ box: { color: "#000000", opacity: 1, height: 300, base: 200 } });
    act(() => player.set({ time: 1, playing: false }));
    const { container } = render(<ShiftedLayer texts={[item]}><video /></ShiftedLayer>);
    const layer = container.querySelector("video")!.parentElement as HTMLElement;
    expect(layer.getAttribute("style")).toContain("translateY");
  });

  it("leaves the video alone with no resize or outside the item", () => {
    const same = text({ box: { color: "#000000", opacity: 1, height: 200, base: 200 } });
    act(() => player.set({ time: 1, playing: false }));
    expect(render(<ShiftedLayer texts={[same]}><video /></ShiftedLayer>).container.querySelector("video")!.parentElement!.style.transform).toBe("");
    const moved = text({ box: { color: "#000000", opacity: 1, height: 300, base: 200 } });
    act(() => player.set({ time: 9, playing: false }));
    expect(render(<ShiftedLayer texts={[moved]}><video /></ShiftedLayer>).container.querySelector("video")!.parentElement!.style.transform).toBe("");
  });
});
