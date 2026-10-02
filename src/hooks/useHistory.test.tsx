// @vitest-environment jsdom
import { StrictMode, type ReactNode } from "react";
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useHistory } from "./useHistory";

// Rendered in StrictMode like the app, which runs state updaters twice in development.
const strict = ({ children }: { children: ReactNode }) => <StrictMode>{children}</StrictMode>;

const setup = (initial = 0, max = 50) => renderHook(() => useHistory(initial, max), { wrapper: strict });

describe("useHistory", () => {
  it("undoes one edit per undo", () => {
    const { result } = setup();
    act(() => result.current.set(1));
    act(() => result.current.set(2));
    act(() => result.current.undo());
    expect(result.current.state).toBe(1);
    act(() => result.current.undo());
    expect(result.current.state).toBe(0);
    expect(result.current.canUndo).toBe(false);
  });

  it("redoes what was undone, and a new edit clears the redo list", () => {
    const { result } = setup();
    act(() => result.current.set(1));
    act(() => result.current.undo());
    expect(result.current.canRedo).toBe(true);
    act(() => result.current.redo());
    expect(result.current.state).toBe(1);
    act(() => result.current.undo());
    act(() => result.current.set(5));
    expect(result.current.canRedo).toBe(false);
  });

  it("applies functional updates to the latest state, one history entry each", () => {
    const { result } = setup(10);
    act(() => {
      result.current.set((n) => n + 1);
      result.current.set((n) => n + 1);
    });
    expect(result.current.state).toBe(12);
    act(() => result.current.undo());
    expect(result.current.state).toBe(11);
    act(() => result.current.undo());
    expect(result.current.state).toBe(10);
    expect(result.current.canUndo).toBe(false);
  });

  it("ignores a set that does not change the state", () => {
    const { result } = setup(3);
    act(() => result.current.set(3));
    expect(result.current.canUndo).toBe(false);
  });

  it("keeps only the newest entries", () => {
    const { result } = setup(0, 3);
    for (let i = 1; i <= 6; i++) act(() => result.current.set(i));
    for (let i = 0; i < 10; i++) act(() => result.current.undo());
    expect(result.current.state).toBe(3);
  });

  it("starts over on reset", () => {
    const { result } = setup();
    act(() => result.current.set(1));
    act(() => result.current.reset(9));
    expect(result.current.state).toBe(9);
    expect(result.current.canUndo).toBe(false);
    expect(result.current.canRedo).toBe(false);
  });
});
