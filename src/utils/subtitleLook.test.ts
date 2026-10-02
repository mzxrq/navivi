import { describe, expect, it } from "vitest";
import { subtitleStyleOf } from "./subtitleLook";
import { toManifest, emptyTimeline } from "../features/editor/model";

describe("subtitleStyleOf", () => {
  it("keeps only the caption settings that are set", () => {
    expect(subtitleStyleOf({ subtitle_font: "Meiryo", subtitle_font_size: 20, fps: 30, subtitle_bold: false })).toEqual({
      subtitle_font: "Meiryo",
      subtitle_font_size: 20,
      subtitle_bold: false,
    });
  });

  it("is empty for a project that never touched them, so the exporter's defaults apply", () => {
    expect(subtitleStyleOf({ fps: 30 })).toEqual({});
  });
});

describe("the caption style in timeline.json", () => {
  it("is written next to burn_subtitles for the exporter", () => {
    const style = { subtitle_font_size: 24, subtitle_color: "&H0000FFFF" };
    expect(toManifest("Trip", emptyTimeline(), style).subtitle_style).toEqual(style);
  });

  it("is left out when no settings were given", () => {
    expect(JSON.parse(JSON.stringify(toManifest("Trip", emptyTimeline())))).not.toHaveProperty("subtitle_style");
  });
});
