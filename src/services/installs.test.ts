import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ callSidecar: vi.fn(), invoke: vi.fn(() => Promise.resolve("Cancelled")) }));
vi.mock("./sidecar", () => ({ callSidecar: mocks.callSidecar }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: mocks.invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen: vi.fn(() => Promise.resolve(() => {})) }));

import { cancelInstall, getInstalls, parseProgress, resetInstalls, startInstall } from "./installs";
import { parseDownloadLine } from "./setup";

afterEach(resetInstalls);

describe("parseProgress", () => {
  it("reads the installer's progress line", () => {
    expect(parseProgress("[progress] 2/4|installing torch (CPU)")).toEqual({ fraction: 0.5, step: "installing torch (CPU)" });
  });
  it("ignores any other line", () => {
    expect(parseProgress("2026-10-08 [INFO] Kokoro setup: creating the environment")).toBeNull();
  });
});

describe("cancelInstall", () => {
  it("stops the process and drops the job instead of showing a failure", async () => {
    let finish: (v: unknown) => void = () => {};
    mocks.callSidecar.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const started = startInstall("kokoro", "Kokoro-82M", "tts_install_kokoro");
    await vi.waitFor(() => expect(mocks.callSidecar).toHaveBeenCalled());
    await cancelInstall("kokoro");
    expect(mocks.invoke).toHaveBeenCalledWith("cancel_python_blueprint");
    finish({ success: false, error: "Process was cancelled", cancelled: true });
    await started;
    expect(getInstalls()).toHaveLength(0);
  });

  it("does nothing for an install that is not running", async () => {
    mocks.invoke.mockClear();
    await cancelInstall("nothing");
    expect(mocks.invoke).not.toHaveBeenCalled();
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
