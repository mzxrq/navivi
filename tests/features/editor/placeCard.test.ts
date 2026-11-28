import { describe, expect, it } from "vitest";
import {
  cardOf, carryOverLooks, TextClip, TimelineData, timelineFromPipeline, toManifest,
} from "../../../src/features/editor/model";

const picture = { path: ".navivi/hud/place_1.png", x: -14, y: -18, width: 400, height: 190, text: "神社" };
const item: TextClip = {
  id: "t", segmentId: "a", start: 0, end: 5, kind: "place", title: { text: "神社" }, subtitle: { text: "" }, picture,
};

describe("themed place card", () => {
  it("is shown only while the item's words are still the card's", () => {
    expect(cardOf(item)).toEqual(picture);
    expect(cardOf({ ...item, title: { text: "新しい名前" } })).toBeUndefined();
    expect(cardOf({ ...item, picture: undefined })).toBeUndefined();
  });

  const timeline = (texts: TextClip[]): TimelineData => ({
    segments: [{ id: "a", kind: "attraction", name: "a", video: "a.mp4", duration: 6, trimStart: 0, trimEnd: 0 } as any],
    subtitles: [], texts, music: null,
  });

  it("goes with the item into timeline.json for the export", () => {
    const out = toManifest("p", timeline([item]));

    expect(out.texts[0].picture).toEqual(picture);
  });

  it("is read from the render's own timeline.json", async () => {
    const out = await timelineFromPipeline(
      { video_tracks: [{ file_path: "a.mp4", clip_name: "04_attraction_00_a", texts: [item] }] },
      async () => 6,
    );

    expect(out.texts[0].picture).toEqual(picture);
  });

  it("comes from the new render, whatever look was carried over from the old timeline", () => {
    const fresh = { ...picture, path: ".navivi/hud/place_2.png" };

    const out = carryOverLooks(timeline([{ ...item, margin_v: 40 }]), timeline([{ ...item, picture: fresh }]));

    expect(out.texts[0].picture).toEqual(fresh);
  });
});
