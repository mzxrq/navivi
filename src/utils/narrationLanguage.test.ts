import { describe, expect, it } from "vitest";
import { resolveNarrationLanguage, textLanguage } from "./narrationLanguage";

describe("narration language", () => {
  it("reads the language of the texts", () => {
    expect(textLanguage(["Kyoshi Sta.", "Mt. Iimori (飯盛山)"])).toBe("en");
    expect(textLanguage(["三段壁展望台", "白良浜"])).toBe("ja");
    expect(textLanguage(["", "12:30"])).toBeNull();
  });

  it("uses the setting when it names a language, else the texts, else the app language", () => {
    expect(resolveNarrationLanguage("ja", ["Kyoshi Sta."], "en")).toBe("ja");
    expect(resolveNarrationLanguage("en", ["白良浜"], "ja")).toBe("en");
    expect(resolveNarrationLanguage("auto", ["Kyoshi Sta."], "ja")).toBe("en");
    expect(resolveNarrationLanguage(undefined, [], "ja-JP")).toBe("ja");
    expect(resolveNarrationLanguage(undefined, [], "en")).toBe("en");
  });
});
