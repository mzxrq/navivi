import { beforeEach, describe, expect, it, vi } from "vitest";

const invoke = vi.hoisted(() => vi.fn());
vi.mock("@tauri-apps/api/core", () => ({ invoke }));

import { callSidecar, callSidecarShared, parseReply, runStage } from "./sidecar";

beforeEach(() => {
  invoke.mockReset();
});

describe("parseReply", () => {
  it("reads the last line and ignores progress output before it", () => {
    const out = "[00:01] [1/7] Parsing GPS\nwarning: something\n" + JSON.stringify({ success: true, words: [] }) + "\n";
    expect(parseReply(out)).toEqual({ success: true, words: [] });
  });

  it("passes a failure reply through", () => {
    expect(parseReply(JSON.stringify({ success: false, error: "no model" }))).toEqual({ success: false, error: "no model" });
  });

  it("turns output that is not a reply into an error", () => {
    expect(parseReply("Traceback (most recent call last):")).toMatchObject({ success: false });
    expect(parseReply("")).toMatchObject({ success: false });
    expect(parseReply(JSON.stringify({ voices: [] }))).toMatchObject({ success: false });
  });
});

describe("runStage", () => {
  it("puts the project file in `action` and the mode in `payload`, as the Rust command expects", async () => {
    invoke.mockResolvedValue("done");
    await expect(runStage("C:/p/job_config.json", "tts-all")).resolves.toBe("done");
    expect(invoke).toHaveBeenCalledWith("run_python_blueprint", { action: "C:/p/job_config.json", payload: "tts-all" });
  });

  it("rejects with the process error", async () => {
    invoke.mockImplementation(async () => {
      throw "Process terminated";
    });
    await expect(runStage("c.json", "concat")).rejects.toBe("Process terminated");
  });
});

describe("callSidecar", () => {
  it("sends a string input as is and anything else as JSON", async () => {
    invoke.mockResolvedValue(JSON.stringify({ success: true }));
    await callSidecar("extract_words", "三段壁");
    await callSidecar("get_furigana", ["三段壁", "白浜"]);
    await callSidecar("tts_voices_list");
    expect(invoke.mock.calls.map((c) => c[1])).toEqual([
      { action: "extract_words", payload: "三段壁" },
      { action: "get_furigana", payload: JSON.stringify(["三段壁", "白浜"]) },
      { action: "tts_voices_list", payload: "{}" },
    ]);
  });

  it("returns the parsed reply", async () => {
    invoke.mockResolvedValue("log line\n" + JSON.stringify({ success: true, readings: { 白浜: "しらはま" } }));
    await expect(callSidecar("get_furigana", ["白浜"])).resolves.toEqual({ success: true, readings: { 白浜: "しらはま" } });
  });

  it("marks a call killed by a newer one as cancelled", async () => {
    invoke.mockImplementation(async () => {
      throw "Process was cancelled";
    });
    await expect(callSidecar("tts_voices_list")).resolves.toEqual({ success: false, error: "Process was cancelled", cancelled: true });
  });

  it("does not mark other failures as cancelled", async () => {
    invoke.mockImplementation(async () => {
      throw new Error("TTS server did not start");
    });
    const reply = await callSidecar("tts_voice_preview", { voice: "test1" });
    expect(reply).toEqual({ success: false, error: "TTS server did not start", cancelled: false });
  });
});

describe("callSidecarShared", () => {
  const reply = JSON.stringify({ success: true, voices: [] });

  it("lets identical overlapping requests share one run", async () => {
    let finish: (v: string) => void = () => {};
    invoke.mockReturnValue(new Promise<string>((r) => (finish = r)));
    const first = callSidecarShared("tts_voices_list");
    const second = callSidecarShared("tts_voices_list");
    finish(reply);
    expect(await first).toEqual({ success: true, voices: [] });
    expect(await second).toEqual({ success: true, voices: [] });
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("keeps different requests apart", async () => {
    invoke.mockResolvedValue(reply);
    await Promise.all([callSidecarShared("tts_voices_list"), callSidecarShared("get_furigana", ["a"]), callSidecarShared("get_furigana", ["b"])]);
    expect(invoke).toHaveBeenCalledTimes(3);
  });

  it("runs again once the first request has finished", async () => {
    invoke.mockResolvedValue(reply);
    await callSidecarShared("tts_voices_list");
    await callSidecarShared("tts_voices_list");
    expect(invoke).toHaveBeenCalledTimes(2);
  });
});

describe("systemRamGb", () => {
  it("asks the sidecar once and remembers the answer", async () => {
    vi.resetModules();
    const { systemRamGb } = await import("./sidecar");
    invoke.mockResolvedValue(JSON.stringify({ success: true, ram_total_gb: 16 }));
    await expect(systemRamGb()).resolves.toBe(16);
    await expect(systemRamGb()).resolves.toBe(16);
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it("asks again after a failed attempt", async () => {
    vi.resetModules();
    const { systemRamGb } = await import("./sidecar");
    invoke.mockRejectedValueOnce("Process was cancelled").mockResolvedValue(JSON.stringify({ success: true, ram_total_gb: 8 }));
    await expect(systemRamGb()).resolves.toBeUndefined();
    await expect(systemRamGb()).resolves.toBe(8);
  });
});
