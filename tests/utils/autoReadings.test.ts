import { describe, expect, it } from "vitest";
import { mergeAutoReadings, narrationText } from "../../src/utils/autoReadings";

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

  it("updates an auto word's reading when the scan reads it differently", () => {
    const current = [{ word: "神福寺跡", reading: "かみふくてらあと", auto: true }];
    expect(mergeAutoReadings(current, [{ word: "神福寺跡", reading: "しんぷくじせき" }], [])).toEqual([
      { word: "神福寺跡", reading: "しんぷくじせき", auto: true },
    ]);
  });

  it("never adds a word again that is already there by hand, spaced or not", () => {
    const manual = [{ word: "友ヶ島小展望台", reading: "ともがしましょうてんぼうだい" }];
    const scan = [
      { word: "友ヶ島 小展望台", reading: "ともがしま しょうてんぼうだい" },
      { word: "友ヶ島小展望台", reading: "ともがしましょうてんぼうだい" },
    ];
    expect(mergeAutoReadings(manual, scan, [])).toBeNull();
  });

  it("drops an auto copy of a hand-typed word and an auto copy of another auto word", () => {
    const current = [
      { word: "友ヶ島", reading: "ともがしま", auto: true },
      { word: "友ヶ島", reading: "ともがしま" },
      { word: "北垂水小展望台", reading: "きたたるみしょうてんぼうだい", auto: true },
      { word: "北垂水 小展望台", reading: "きたたるみ しょうてんぼうだい", auto: true },
    ];
    const scan = [
      { word: "友ヶ島", reading: "ともがしま" },
      { word: "北垂水小展望台", reading: "きたたるみしょうてんぼうだい" },
      { word: "北垂水 小展望台", reading: "きたたるみ しょうてんぼうだい" },
    ];
    expect(mergeAutoReadings(current, scan, [])).toEqual([
      { word: "友ヶ島", reading: "ともがしま" },
      { word: "北垂水小展望台", reading: "きたたるみしょうてんぼうだい", auto: true },
    ]);
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
