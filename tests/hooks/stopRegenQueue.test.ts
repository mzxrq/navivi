import { describe, expect, it, vi } from "vitest";

vi.mock("../../src/hooks/useWorkspace", () => ({ useWorkspace: () => ({}) }));
vi.mock("../../src/hooks/useUI", () => ({ useUI: () => ({}) }));

import { enqueue, moveQueued, removeQueued } from "../../src/hooks/useStopRegen";

describe("make-again queue", () => {
  it("runs jobs one at a time in order, skips duplicates, and can be rearranged", async () => {
    const ran: string[] = [];
    let release!: () => void;
    const first = new Promise<void>((r) => (release = r));
    const job = (name: string, wait?: Promise<void>) => ({ index: name, kind: "voice", run: async () => { ran.push(name); await wait; } }) as never;

    expect(enqueue(job("a", first))).toBe(false);
    expect(enqueue(job("b"))).toBe(true);
    expect(enqueue(job("c"))).toBe(true);
    expect(enqueue(job("d"))).toBe(true);
    expect(enqueue(job("b"))).toBeNull(); // already waiting
    moveQueued(2, -1); // waiting: b, d, c
    removeQueued(0); // waiting: d, c
    release();
    await vi.waitFor(() => expect(ran).toEqual(["a", "d", "c"]));
  });
});
