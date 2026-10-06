import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/plugin-http", () => ({ fetch: vi.fn() }));
vi.mock("@tauri-apps/api/app", () => ({ getVersion: () => Promise.resolve("1.0.0") }));
vi.mock("@tauri-apps/api/path", () => ({ documentDir: () => Promise.resolve("C:/Docs"), join: (...p: string[]) => Promise.resolve(p.join("/")) }));
vi.mock("@tauri-apps/plugin-fs", () => ({ mkdir: vi.fn(), writeFile: vi.fn() }));

import { fileNameFor, findPlacePhotos, isFreeLicense, JsonGetter, sameName, stripHtml } from "./placePhotos";

const page = (title: string, over: Record<string, unknown> = {}, meta: Record<string, string> = {}) => ({
  title,
  imageinfo: [
    {
      width: 4000,
      height: 2600,
      mime: "image/jpeg",
      thumburl: `https://thumb/${encodeURIComponent(title)}`,
      descriptionurl: `https://commons.wikimedia.org/wiki/${title.replace(/ /g, "_")}`,
      extmetadata: { LicenseShortName: { value: meta.license ?? "CC BY-SA 4.0" }, Artist: { value: meta.artist ?? '<a href="x">Taro</a>' } },
      ...over,
    },
  ],
});

// A canned Wikimedia: answers by looking at what the URL asks for.
const wiki = (answers: { articles?: any[]; geo?: any[]; search?: any[]; files: any[] }) => {
  const calls: string[] = [];
  const get: JsonGetter = async (url) => {
    calls.push(url);
    const u = new URL(url);
    const q = u.searchParams;
    if (u.host === "commons.wikimedia.org" && q.get("list") === "geosearch") return { query: { geosearch: answers.geo ?? [] } };
    if (u.host === "commons.wikimedia.org" && q.get("list") === "search") return { query: { search: answers.search ?? [] } };
    if (u.host === "commons.wikimedia.org" && q.get("prop") === "imageinfo") {
      const asked = (q.get("titles") ?? "").split("|");
      return { query: { pages: answers.files.filter((f) => asked.includes(f.title)) } };
    }
    return { query: { pages: answers.articles ?? [] } }; // a wikipedia article lookup
  };
  return Object.assign(get, { calls });
};

describe("helpers", () => {
  it("strips markup from a photographer's name", () => {
    expect(stripHtml('<a href="u">Taro &amp; Co</a>\n')).toBe("Taro & Co");
  });

  it("matches an article to a stop by name, either way round, but not unrelated or very short names", () => {
    expect(sameName("三段壁展望台", "三段壁")).toBe(true);
    expect(sameName("Sandanbeki", "Sandanbeki Cliff")).toBe(true);
    expect(sameName("白浜バスセンター", "千畳敷 (和歌山県)")).toBe(false);
    expect(sameName("駅", "駅")).toBe(false);
  });

  it("accepts free licenses that allow cropping and credit, refuses the rest", () => {
    for (const ok of ["CC BY-SA 4.0", "CC BY 2.5", "CC0", "Public domain", "PD-old-70", "Attribution"]) expect(isFreeLicense(ok), ok).toBe(true);
    for (const no of ["CC BY-NC 4.0", "CC BY-ND 4.0", "All rights reserved", "Fair use", ""]) expect(isFreeLicense(no), no).toBe(false);
  });

  it("makes safe file names", () => {
    expect(fileNameFor('File:A/B: "x"?.jpg', "image/jpeg")).toBe("A B x.jpg");
    expect(fileNameFor("File:Plan.PNG", "image/png")).toBe("Plan.png");
  });
});

describe("findPlacePhotos", () => {
  it("puts the article's lead photo first, then nearby photos, with credit and license", async () => {
    const get = wiki({
      articles: [
        { title: "三段壁", pageimage: "Sandanbeki.jpg" },
        { title: "千畳敷", pageimage: "Senjojiki.jpg" },
      ],
      geo: [
        { title: "File:Near.jpg", dist: 40 },
        { title: "File:Far.jpg", dist: 290 },
      ],
      files: [page("File:Sandanbeki.jpg"), page("File:Near.jpg"), page("File:Far.jpg")],
    });
    const found = await findPlacePhotos({ name: "三段壁展望台", lat: 33.67, lng: 135.33 }, { get, limit: 3 });
    expect(found.map((f) => f.title)).toEqual(["File:Sandanbeki.jpg", "File:Near.jpg"]); // Far.jpg is 290 m away and has nothing to do with the name
    expect(found[0]).toMatchObject({ author: "Taro", license: "CC BY-SA 4.0", url: expect.stringContaining("commons.wikimedia.org") });
  });

  it("keeps a nearby file that carries the stop's name even when it is further away", async () => {
    const get = wiki({ geo: [{ title: "File:Sandanbeki cliff view.jpg", dist: 250 }], files: [page("File:Sandanbeki cliff view.jpg")] });
    expect((await findPlacePhotos({ name: "Sandanbeki", lat: 1, lng: 2 }, { get })).map((f) => f.title)).toEqual(["File:Sandanbeki cliff view.jpg"]);
  });

  it("ignores an article of the same name that is far away (a namesake in another country)", async () => {
    const get = wiki({
      articles: [
        { title: "孝子駅 (韓国)", pageimage: "Korea.jpg", coordinates: [{ lat: 37.7, lon: 127.04 }] },
        { title: "孝子駅", pageimage: "Japan.jpg", coordinates: [{ lat: 34.29, lon: 135.15 }] },
      ],
      files: [page("File:Korea.jpg"), page("File:Japan.jpg")],
    });
    const found = await findPlacePhotos({ name: "孝子駅", lat: 34.29, lng: 135.15 }, { get });
    expect(found.map((f) => f.title)).toEqual(["File:Japan.jpg"]);
  });

  it("does not fill every slot with shots from one series", async () => {
    const get = wiki({
      geo: [
        { title: "File:Hongu 122.jpg", dist: 1 },
        { title: "File:Hongu 123.jpg", dist: 2 },
        { title: "File:Hongu 124.jpg", dist: 3 },
        { title: "File:Other view.jpg", dist: 30 },
      ],
      files: ["Hongu 122", "Hongu 123", "Hongu 124", "Other view"].map((n) => page(`File:${n}.jpg`)),
    });
    const found = await findPlacePhotos({ name: "Hongu", lat: 1, lng: 2 }, { get, limit: 2 });
    expect(found.map((f) => f.title)).toEqual(["File:Hongu 122.jpg", "File:Other view.jpg"]);
  });

  it("drops maps, logos, small images, other formats and non-free files", async () => {
    const get = wiki({
      geo: [1, 2, 3, 4, 5, 6].map((n) => ({ title: `File:C${n}.jpg`, dist: n })).concat([{ title: "File:Locator map of X.jpg", dist: 1 }]),
      files: [
        page("File:C1.jpg", { width: 600, height: 400 }),
        page("File:C2.jpg", { mime: "image/svg+xml" }),
        page("File:C3.jpg", {}, { license: "CC BY-NC 4.0" }),
        page("File:Locator map of X.jpg"),
        page("File:C5.jpg"),
        { title: "File:C6.jpg", missing: true },
      ],
    });
    const found = await findPlacePhotos({ name: "X place", lat: 1, lng: 2 }, { get });
    expect(found.map((f) => f.title)).toEqual(["File:C5.jpg"]);
  });

  it("prefers landscape photos", async () => {
    const get = wiki({
      geo: [
        { title: "File:Tall.jpg", dist: 10 },
        { title: "File:Wide.jpg", dist: 11 },
      ],
      files: [page("File:Tall.jpg", { width: 2000, height: 3000 }), page("File:Wide.jpg", { width: 3000, height: 2000 })],
    });
    const found = await findPlacePhotos({ name: "Somewhere", lat: 1, lng: 2 }, { get });
    expect(found[0].title).toBe("File:Wide.jpg");
  });

  it("for a guessed position searches by name only, never by coordinates, and offers at most one photo", async () => {
    const get = wiki({ search: [{ title: "File:Named.jpg" }, { title: "File:Named other.jpg" }], files: [page("File:Named.jpg"), page("File:Named other.jpg")] });
    const found = await findPlacePhotos({ name: "Sainen-ji", lat: 0, lng: 0, uncertain: true }, { get, limit: 3 });
    expect(found).toHaveLength(1);
    expect(get.calls.some((u) => /geosearch/.test(u))).toBe(false);
  });

  it("for a known position takes articles from around that position, not from a name search", async () => {
    const get = wiki({ files: [] });
    await findPlacePhotos({ name: "孝子駅", lat: 34.29, lng: 135.15 }, { get });
    const wikipedia = get.calls.filter((u) => u.includes("wikipedia.org"));
    expect(wikipedia.length).toBeGreaterThan(0);
    expect(wikipedia.every((u) => u.includes("generator=geosearch"))).toBe(true);
  });

  it("answers with nothing when nothing is found, and survives a failing lookup", async () => {
    expect(await findPlacePhotos({ name: "Nowhere", lat: 1, lng: 2 }, { get: wiki({ files: [] }) })).toEqual([]);
    const flaky: JsonGetter = async (url) => {
      if (url.includes("wikipedia.org")) throw new Error("down");
      const q = new URL(url).searchParams;
      if (q.get("list") === "geosearch") return { query: { geosearch: [{ title: "File:Ok.jpg", dist: 5 }] } };
      if (q.get("prop") === "imageinfo") return { query: { pages: [page("File:Ok.jpg")] } };
      return { query: {} };
    };
    expect((await findPlacePhotos({ name: "Somewhere", lat: 1, lng: 2 }, { get: flaky })).map((f) => f.title)).toEqual(["File:Ok.jpg"]);
  });

  it("asks one question at a time and stops when aborted", async () => {
    let running = 0;
    let most = 0;
    const get: JsonGetter = async () => {
      most = Math.max(most, ++running);
      await new Promise((r) => setTimeout(r, 2));
      running--;
      return { query: {} };
    };
    await findPlacePhotos({ name: "Somewhere", lat: 1, lng: 2 }, { get });
    expect(most).toBe(1);
    const stop = new AbortController();
    stop.abort();
    const refuse: JsonGetter = async (_u, signal) => {
      if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
      return { query: {} };
    };
    await expect(findPlacePhotos({ name: "Somewhere", lat: 1, lng: 2 }, { get: refuse, signal: stop.signal })).rejects.toThrow();
  });
});
