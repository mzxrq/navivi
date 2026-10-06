import { describe, expect, it } from "vitest";
import { mergeAutoReadings, narrationText } from "./autoReadings";

describe("mergeAutoReadings", () => {
  it("adds new words as auto", () => {
    expect(mergeAutoReadings([], [{ word: "三段壁", reading: "さんだんへき" }], [])).toEqual([
      { word: "三段壁", reading: "さんだんへき", auto: true },
    ]);
  });

  it("never changes a manual reading", () => {
    const manual = [{ word: "三段壁", reading: "さんだんべき" }];
    expect(mergeAutoReadings(manual, [{ word: "三段壁", reading: "さんだんへき" }], [])).toBeNull();
  });

  it("drops auto words no script uses, keeps manual ones", () => {
    const current = [
      { word: "海", reading: "うみ", auto: true },
      { word: "加太", reading: "かだ" },
    ];
    expect(mergeAutoReadings(current, [], [])).toEqual([{ word: "加太", reading: "かだ" }]);
  });

  it("leaves words the shared dictionary covers to it", () => {
    const current = [{ word: "白良浜", reading: "しろらはま", auto: true }];
    const shared = [{ word: "白良浜" }];
    expect(mergeAutoReadings(current, [{ word: "白良浜", reading: "しろらはま" }], shared)).toEqual([]);
    expect(mergeAutoReadings([], [{ word: "白良浜", reading: "しろらはま" }], shared)).toBeNull();
  });

  it("skips words without a reading", () => {
    expect(mergeAutoReadings([], [{ word: "謎", reading: "" }], [])).toBeNull();
  });

  it("returns null when nothing changed", () => {
    const current = [{ word: "海", reading: "うみ", auto: true }];
    expect(mergeAutoReadings(current, [{ word: "海", reading: "うみ" }], [])).toBeNull();
  });
});

describe("narrationText", () => {
  it("joins the overview and every script, skipping blanks", () => {
    expect(
      narrationText([{ arrivingNarration: " 海へ ", attractionNarration: "" }, { attractionNarration: "山" }], "旅"),
    ).toBe("旅\n海へ\n山");
  });
});
