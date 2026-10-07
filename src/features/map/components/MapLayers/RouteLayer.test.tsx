// @vitest-environment jsdom
import { useRef } from "react";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RouteLayer } from "./RouteLayer";
import type { LegElevation } from "../../../../utils/elevation";

const state = vi.hoisted(() => ({
  settings: { show_route_heatmap: false } as any,
  routeSegments: [] as any[],
  waypoints: [] as any[],
}));

vi.mock("../../../../hooks/useWorkspace", () => ({ useWorkspace: () => state }));

// react-map-gl throws "source id changed" when one <Source> element is re-rendered with another id.
vi.mock("react-map-gl/mapbox", () => ({
  Source: ({ id, data, children }: any) => {
    const first = useRef(id);
    if (first.current !== id) throw new Error("source id changed");
    return <div data-source={id} data-features={data?.features?.length ?? 0}>{children}</div>;
  },
  Layer: ({ id }: any) => <i data-layer={id} />,
}));

const legPositions: [number, number][] = Array.from({ length: 40 }, (_, i) => [34, 135 + i * 0.0001]);
const leg: LegElevation = { positions: legPositions, ele: legPositions.map((_, i) => i * 0.9), source: "recorded" };

describe("RouteLayer heatmap", () => {
  it("can be switched on and off without remounting a source under a new id", () => {
    state.routeSegments = [{ positions: legPositions, mode: "draw" }];
    state.settings = { show_route_heatmap: false };
    const { rerender, container } = render(<RouteLayer uploadedRouteLine={[]} routePoints={[]} legs={[leg]} />);
    const features = (id: string) => Number(container.querySelector(`[data-source="${id}"]`)?.getAttribute("data-features"));
    expect(features("route-gradient-heatmap-source")).toBe(0);
    expect(features("dynamic-routes")).toBe(1);

    state.settings = { show_route_heatmap: true };
    expect(() => rerender(<RouteLayer uploadedRouteLine={[]} routePoints={[]} legs={[leg]} />)).not.toThrow();
    expect(features("route-gradient-heatmap-source")).toBe(39);
    expect(features("dynamic-routes")).toBe(0);

    state.settings = { show_route_heatmap: false };
    rerender(<RouteLayer uploadedRouteLine={[]} routePoints={[]} legs={[leg]} />);
    expect(features("dynamic-routes")).toBe(1);
  });

  it("keeps legs without elevation drawn in their own style while the heatmap is on", () => {
    state.routeSegments = [
      { positions: legPositions, mode: "draw" },
      { positions: legPositions, mode: "driving" },
    ];
    state.settings = { show_route_heatmap: true };
    const noEle: LegElevation = { positions: legPositions, ele: null, source: null };
    const { container } = render(<RouteLayer uploadedRouteLine={[]} routePoints={[]} legs={[leg, noEle]} />);
    expect(container.querySelector('[data-source="dynamic-routes"]')?.getAttribute("data-features")).toBe("1");
  });
});
