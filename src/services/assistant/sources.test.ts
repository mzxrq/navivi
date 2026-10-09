// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";

vi.mock("@tauri-apps/plugin-fs", () => ({ readTextFile: vi.fn() }));
vi.mock("@tauri-apps/plugin-http", () => ({ fetch: vi.fn() }));
vi.mock("../sidecar", () => ({ callSidecar: vi.fn() }));

import { callSidecar } from "../sidecar";
import { denoise, htmlToText, isSupportedDocument, isWebAddress, readSource } from "./sources";

describe("htmlToText", () => {
  it("drops scripts, styles and navigation and keeps the article", () => {
    const { title, text } = htmlToText(`<html><head><title> Katsuragi  Trail </title><style>p{}</style></head><body>
      <nav>Home | About</nav><script>var x=1</script>
      <article><h1>Seven temples</h1><p>Start at   the first temple.</p><p>Walk on.<br>Rest.</p></article>
      <footer>copyright</footer></body></html>`);
    expect(title).toBe("Katsuragi Trail");
    expect(text).toBe("Seven temples\nStart at the first temple.\nWalk on.\nRest.");
  });

  it("falls back to the body when there is no article or main", () => {
    expect(htmlToText("<body><div>One</div><div>Two</div></body>").text).toBe("One\nTwo");
  });
});

describe("source detection", () => {
  it("tells web addresses from paths", () => {
    expect(isWebAddress(" https://example.com/a?b=1 ")).toBe(true);
    expect(isWebAddress("C:\\docs\\a.pdf")).toBe(false);
    expect(isWebAddress("see https://example.com")).toBe(false);
  });

  it("accepts the document types and nothing else", () => {
    for (const ok of ["a.pdf", "C:\\x\\Trip.DOCX", "/home/u/notes.md", "b.txt", "c.csv"]) expect(isSupportedDocument(ok)).toBe(true);
    for (const bad of ["a.exe", "pdf", "photo.jpg", "C:\\x.y\\noext"]) expect(isSupportedDocument(bad)).toBe(false);
  });
});

describe("readSource", () => {
  it("sends PDF and Word files to the sidecar", async () => {
    vi.mocked(callSidecar).mockResolvedValue({ success: true, text: "route text", truncated: true } as never);
    expect(await readSource("C:\\a b\\guide.pdf")).toEqual({ name: "guide.pdf", text: "route text", truncated: true });
    expect(callSidecar).toHaveBeenCalledWith("read_document", "C:\\a b\\guide.pdf");
  });

  it("tries again when another sidecar call cancels the read, and gives up with a clear message", async () => {
    const cancelled = { success: false, error: "Process was cancelled", cancelled: true } as never;
    vi.mocked(callSidecar).mockReset().mockResolvedValueOnce(cancelled).mockResolvedValueOnce(cancelled).mockResolvedValue({ success: true, text: "ok", truncated: false } as never);
    expect((await readSource("a.pdf")).text).toBe("ok");
    vi.mocked(callSidecar).mockReset().mockResolvedValue(cancelled);
    await expect(readSource("a.pdf")).rejects.toThrow("interrupted");
    expect(callSidecar).toHaveBeenCalledTimes(5);
  }, 15000);

  it("passes the sidecar's error on and rejects unsupported files", async () => {
    vi.mocked(callSidecar).mockResolvedValue({ success: false, error: "This PDF is password protected." });
    await expect(readSource("x.pdf")).rejects.toThrow("password protected");
    await expect(readSource("x.exe")).rejects.toThrow("not a supported file");
  });
});

describe("denoise", () => {
  it("drops numbers and symbol lines and collapses labels printed twice", () => {
    expect(denoise(["0.25", "1.20ˠ", "Kyoshi Sta.Kyoshi Sta.", "Mt. Iimori", "ˡ", "00"].join("\n"))).toBe("Kyoshi Sta.\nMt. Iimori");
  });
});
