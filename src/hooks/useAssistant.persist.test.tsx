// @vitest-environment jsdom
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const files = vi.hoisted(() => new Map<string, string>());
const ws = vi.hoisted(() => ({ metadata: { directory_path: "", project_name: "", project_id: "" } as any }));
const brain = vi.hoisted(() => ({ converse: vi.fn() }));

vi.mock("@tauri-apps/api/path", () => ({ join: async (...parts: string[]) => parts.join("/") }));
vi.mock("@tauri-apps/plugin-fs", () => ({
  exists: async (p: string) => files.has(p),
  readTextFile: async (p: string) => files.get(p) ?? "",
  writeTextFile: async (p: string, text: string) => void files.set(p, text),
  remove: async (p: string) => void files.delete(p),
}));
vi.mock("../services/assistant/converse", () => ({ converse: brain.converse }));
vi.mock("../services/assistant/buildProject", () => ({ buildProject: vi.fn() }));
vi.mock("../services/assistant/sources", () => ({ isSupportedDocument: () => false, readSource: vi.fn() }));
vi.mock("../services/ai/engine", () => ({ aiEngine: () => "model" }));
vi.mock("../services/imageImport", () => ({ isPhoto: () => false }));
vi.mock("../utils/pendingImport", () => ({ setPendingImport: vi.fn() }));
vi.mock("./useUI", () => ({ useUI: () => ({ setCurrentView: vi.fn(), showToast: vi.fn(), currentView: "editor" }) }));
vi.mock("./useWorkspace", () => ({
  useWorkspace: () => ({
    settings: {},
    waypoints: [],
    metadata: ws.metadata,
    setWaypoints: vi.fn(),
    resetWorkspace: vi.fn(),
    updateMetadata: vi.fn(),
    updateSettings: vi.fn(),
    setIsDirty: vi.fn(),
  }),
}));

import { AssistantProvider, useAssistant } from "./useAssistant";

const wrapper = ({ children }: { children: ReactNode }) => <AssistantProvider>{children}</AssistantProvider>;
const open = (dir: string) => (ws.metadata = { ...ws.metadata, directory_path: dir });
const saved = (dir: string) => (files.has(`${dir}/assistant.json`) ? JSON.parse(files.get(`${dir}/assistant.json`)!) : null);
const loaded = () => act(async () => void (await new Promise((r) => setTimeout(r, 60))));
const settle = () => act(async () => void (await new Promise((r) => setTimeout(r, 450))));

afterEach(cleanup); // an old provider would still hear the "project-saved" events of the next test

beforeEach(() => {
  files.clear();
  ws.metadata = { directory_path: "", project_name: "", project_id: "" };
  brain.converse.mockReset().mockResolvedValue({ reply: "ok", patch: {}, ready: false });
});

describe("the assistant chat belongs to its project", () => {
  it("is written into the project folder shortly after each message", async () => {
    open("C:/p/A");
    const { result } = renderHook(() => useAssistant(), { wrapper });
    await loaded();
    await act(async () => result.current.send("hello", []));
    await settle();
    const file = saved("C:/p/A");
    expect(file.version).toBe(1);
    expect(file.messages.map((m: any) => m.text)).toEqual(["hello", "ok"]);
  });

  it("comes back when the project is opened again, and another project has its own", async () => {
    files.set("C:/p/A/assistant.json", JSON.stringify({ version: 1, messages: [{ role: "user", text: "about A" }], brief: { name: "Trip A" }, sources: [], attachments: { gpx: null, photos: [] } }));
    files.set("C:/p/B/assistant.json", JSON.stringify({ version: 1, messages: [{ role: "user", text: "about B" }], sources: [] }));
    open("C:/p/A");
    const { result, rerender } = renderHook(() => useAssistant(), { wrapper });
    await waitFor(() => expect(result.current.messages[0]?.text).toBe("about A"));
    expect(result.current.brief.name).toBe("Trip A");
    open("C:/p/B");
    rerender();
    await waitFor(() => expect(result.current.messages[0]?.text).toBe("about B"));
    expect(result.current.messages).toHaveLength(1);
    open("");
    rerender();
    await waitFor(() => expect(result.current.messages).toHaveLength(0));
    await settle();
    expect(saved("C:/p/A").messages).toHaveLength(1); // closing the project did not touch its chat
  });

  it("does not write start-screen chat anywhere until a project has a folder, then moves with the first save", async () => {
    const { result } = renderHook(() => useAssistant(), { wrapper });
    await act(async () => result.current.send("a day trip", []));
    await settle();
    expect(files.size).toBe(0);
    act(() => void window.dispatchEvent(new CustomEvent("project-saved", { detail: { dir: "C:/p/New" } })));
    await settle();
    expect(saved("C:/p/New").messages.map((m: any) => m.text)).toEqual(["a day trip", "ok"]);
  });

  it("does not let a reply that arrives after switching projects land in the other project", async () => {
    let answer: (v: unknown) => void = () => {};
    brain.converse.mockReturnValue(new Promise((resolve) => (answer = resolve)));
    open("C:/p/A");
    const { result, rerender } = renderHook(() => useAssistant(), { wrapper });
    await loaded();
    act(() => void result.current.send("question for A", []));
    await settle();
    open("C:/p/B");
    rerender();
    await act(async () => answer({ reply: "late answer", patch: { name: "wrong" }, ready: true }));
    await settle();
    expect(result.current.messages).toHaveLength(0);
    expect(result.current.brief.name).toBe("");
    expect(saved("C:/p/B")).toBeNull();
    expect(saved("C:/p/A").messages.map((m: any) => m.text)).toEqual(["question for A"]); // A keeps what was said before the switch
  });

  it("Save As gives the copy its own file and leaves the original's alone", async () => {
    open("C:/p/A");
    const { result } = renderHook(() => useAssistant(), { wrapper });
    await loaded();
    await act(async () => result.current.send("hi", []));
    await settle();
    act(() => void window.dispatchEvent(new CustomEvent("project-saved", { detail: { dir: "C:/p/Copy", saveAs: true } })));
    await settle();
    expect(saved("C:/p/Copy").messages).toHaveLength(2);
    expect(saved("C:/p/A").messages).toHaveLength(2);
  });

  it("a normal save of the open project changes nothing", async () => {
    open("C:/p/A");
    const { result } = renderHook(() => useAssistant(), { wrapper });
    await loaded();
    await act(async () => result.current.send("hi", []));
    await settle();
    const before = files.get("C:/p/A/assistant.json");
    act(() => void window.dispatchEvent(new CustomEvent("project-saved", { detail: { dir: "C:/p/A" } })));
    await settle();
    expect(files.get("C:/p/A/assistant.json")).toBe(before);
  });

  it("starting over deletes the saved chat", async () => {
    open("C:/p/A");
    const { result } = renderHook(() => useAssistant(), { wrapper });
    await loaded();
    await act(async () => result.current.send("hi", []));
    await settle();
    expect(saved("C:/p/A")).not.toBeNull();
    act(() => result.current.reset());
    await settle();
    expect(saved("C:/p/A")).toBeNull();
    expect(result.current.messages).toHaveLength(0);
  });

  it("copes with a damaged file", async () => {
    files.set("C:/p/A/assistant.json", "{not json");
    open("C:/p/A");
    const { result } = renderHook(() => useAssistant(), { wrapper });
    await act(async () => void (await new Promise((r) => setTimeout(r, 50))));
    expect(result.current.messages).toHaveLength(0);
  });
});
