import { describe, expect, it } from "vitest";
import { photoSource, videoCredit, withCredit } from "../../src/utils/photoCredits";

describe("photo credit", () => {
  it("keeps a typed credit and its corner, and drops a hand-typed one that is cleared", () => {
    let c = withCredit(undefined, "a.jpg", { text: "Town office" });
    c = withCredit(c, "a.jpg", { corner: "left" });
    expect(c?.["a.jpg"]).toMatchObject({ text: "Town office", corner: "left" });
    expect(withCredit(c, "a.jpg", { text: "" })).toBeUndefined();
  });

  it("falls back to a found photo's author and license", () => {
    const found = { title: "File:x.jpg", author: "Taro", license: "CC BY 4.0", url: "https://x" };
    expect(videoCredit(found)).toBe("Taro · CC BY 4.0");
    expect(withCredit({ "b.jpg": found }, "b.jpg", { text: "" })?.["b.jpg"].url).toBe("https://x");
  });

  it("takes the page a photo was downloaded from, skipping chats and converters", () => {
    expect(photoSource(["https://www.city.gose.nara.jp/kankou/0000001420.html", "https://www.city.gose.nara.jp/x.jpg"])).toBe("https://www.city.gose.nara.jp/kankou/0000001420.html");
    expect(photoSource(["https://chat.google.com/", "https://chat.usercontent.google.com/download?x=1"])).toBeNull();
    expect(photoSource(["https://convertio.co/", "https://example.org/photo.jpg"])).toBe("https://example.org/photo.jpg");
    expect(photoSource([null, null])).toBeNull();
  });
});