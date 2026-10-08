import { describe, expect, it } from "vitest";
import { parseProgress } from "./installs";
import { parseDownloadLine } from "./setup";

describe("parseProgress", () => {
  it("reads the installer's progress line", () => {
    expect(parseProgress("[progress] 2/4|installing torch (CPU)")).toEqual({ fraction: 0.5, step: "installing torch (CPU)" });
  });
  it("ignores any other line", () => {
    expect(parseProgress("2026-10-08 [INFO] Kokoro setup: creating the environment")).toBeNull();
  });
});

describe("parseDownloadLine", () => {
  it("takes the latest percentage from a Playwright bar", () => {
    expect(parseDownloadLine("|■■■■■■■■        |  40% of 150.8 MiB")).toEqual({ percent: 40, size: "150.8 MiB" });
    expect(parseDownloadLine("|■■        |  10% of 150 MiB\r|■■■■■■■■        |  40% of 150 MiB")?.percent).toBe(40);
  });
  it("does not mistake an ordinary line for a bar", () => {
    expect(parseDownloadLine("Downloading Chromium 140.0 (playwright build v1187)")).toBeNull();
    expect(parseDownloadLine("Resolved 52 packages in 100%")).toBeNull();
  });
});
