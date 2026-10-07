// @vitest-environment jsdom
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const store = vi.hoisted(() => ({ saved: null as unknown, get: vi.fn(), set: vi.fn() }));
vi.mock("../services/db", () => ({ db: { appSettings: { get: store.get, set: store.set } } }));

import { useAppApiKeys } from "./useAppApiKeys";

beforeEach(() => {
  store.saved = null;
  store.get.mockReset().mockImplementation(() => Promise.resolve(store.saved));
  store.set.mockReset().mockResolvedValue(undefined);
});

describe("keys found in an opened project", () => {
  it("fill an empty app-wide key and are saved once", async () => {
    const { result } = renderHook(() => useAppApiKeys());
    await waitFor(() => expect(store.get).toHaveBeenCalled());
    await act(async () => {});
    act(() => result.current.adoptLegacy({ mapbox: "pk.old", ors: "o" }));
    expect(result.current.keys).toEqual({ mapbox: "pk.old", ors: "o" });
    expect(store.set).toHaveBeenCalledWith("api_keys", { mapbox: "pk.old", ors: "o" });
  });

  it("never replace a key the app already has", async () => {
    store.saved = { mapbox: "pk.mine" };
    const { result } = renderHook(() => useAppApiKeys());
    await waitFor(() => expect(result.current.keys.mapbox).toBe("pk.mine"));
    act(() => result.current.adoptLegacy({ mapbox: "pk.other", ors: "o" }));
    expect(result.current.keys).toEqual({ mapbox: "pk.mine", ors: "o" });
    expect(store.set).toHaveBeenLastCalledWith("api_keys", { mapbox: "pk.mine", ors: "o" });
  });

  it("opened before the saved record is read, wait for it and still do not replace a saved key", async () => {
    let finish: (v: unknown) => void = () => {};
    store.get.mockReturnValue(new Promise((resolve) => (finish = resolve)));
    const { result } = renderHook(() => useAppApiKeys());
    act(() => result.current.adoptLegacy({ mapbox: "pk.old", ors: "o" }));
    expect(store.set).not.toHaveBeenCalled();
    await act(async () => finish({ mapbox: "pk.mine" }));
    await waitFor(() => expect(store.set).toHaveBeenCalledWith("api_keys", { mapbox: "pk.mine", ors: "o" }));
  });

  it("change nothing and write nothing when there is nothing to adopt", async () => {
    const { result } = renderHook(() => useAppApiKeys());
    await act(async () => {});
    act(() => result.current.adoptLegacy({}));
    expect(store.set).not.toHaveBeenCalled();
  });
});
