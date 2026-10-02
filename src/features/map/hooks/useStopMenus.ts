import { createElement } from "react";
import { t } from "@lingui/core/macro";
import {
  PRESET_COLORS,
  hexToRgb,
  presetColorNames,
  rgbToHex,
} from "../../../components/ui/ColorSwatches";
import {
  Car,
  Copy,
  CopyPlus,
  CornerDownLeft,
  Edit2,
  Flag,
  Footprints,
  LinkIcon,
  LocateFixed,
  MapPinPlus,
  MapPinned,
  Pencil,
  Plane,
  Route,
  Ruler,
  Ship,
  Trash2,
  X,
} from "../../../components/ui/icons";
import { MenuEntry, separator } from "../../../components/ui/menuItems";
import { useWaypointActions } from "../../../hooks/useWaypointActions";
import { useWorkspace } from "../../../hooks/useWorkspace";
import { RouteMode, Waypoint } from "../../../types/index";

export type ModeOption = { id: RouteMode; icon: typeof Car; label: string };

export function useModeOptions(): ModeOption[] {
  return [
    { id: "walking", icon: Footprints, label: t`Walk` },
    { id: "driving", icon: Car, label: t`Drive` },
    { id: "ferry", icon: Ship, label: t`Ferry` },
    { id: "curve", icon: Plane, label: t`Fly` },
    { id: "direct", icon: Ruler, label: t`Direct` },
    { id: "draw", icon: Pencil, label: t`Draw` },
  ];
}

export const VIA_MODES: (RouteMode | undefined)[] = [undefined, "walking", "driving", "ferry"];

export const legColorable = (wp: Waypoint) => wp.routeMode !== "direct" && wp.routeMode !== "curve";

export function useLegActions() {
  const { waypoints, routeSegments, updateWaypoint } = useWorkspace();

  const startDrawing = (wpId: string) =>
    window.dispatchEvent(new CustomEvent("enter-draw-mode", { detail: { wpId } }));

  const startAdjusting = (wpId: string) =>
    window.dispatchEvent(new CustomEvent("enter-via-mode", { detail: { wpId } }));

  const setLegMode = (wp: Waypoint, mode: RouteMode) => {
    if (mode === wp.routeMode) return;
    if (mode === "draw") {
      const routedWaypoints = waypoints.filter((w) => !w.isStopBy || w.connectToRoute);
      const routedIndex = routedWaypoints.findIndex((w) => w.id === wp.id);
      let newCustomRoute = wp.customRoute || [];
      const seg = routedIndex !== -1 ? routeSegments?.[routedIndex] : undefined;
      if (seg?.positions && seg.positions.length > 2) {
        newCustomRoute = seg.positions.slice(1, -1);
      }
      updateWaypoint(wp.id, { routeMode: "draw", customRoute: newCustomRoute });
      startDrawing(wp.id);
    } else {
      updateWaypoint(wp.id, { routeMode: mode });
    }
  };

  return { startDrawing, startAdjusting, setLegMode };
}

export function useStopMenus() {
  const { waypoints, setWaypoints, updateWaypoint, setActiveWaypointId, setIsDirty } =
    useWorkspace();
  const { addReturnStop } = useWaypointActions();
  const modeOptions = useModeOptions();
  const { startDrawing, startAdjusting, setLegMode } = useLegActions();

  const setStopType = (wpId: string, type: "start" | "end" | "stopby" | "normal") => {
    setWaypoints((prev) => {
      const next = [...prev];
      const index = next.findIndex((w) => w.id === wpId);
      if (index === -1) return prev;
      const wp = next[index];
      if (type === "start") {
        next.splice(index, 1);
        next.unshift({ ...wp, isStopBy: false, connectToRoute: undefined });
      } else if (type === "end") {
        next.splice(index, 1);
        next.push({ ...wp, isStopBy: false, connectToRoute: undefined });
      } else if (type === "stopby") {
        next[index] = { ...wp, isStopBy: true, connectToRoute: false };
      } else {
        next[index] = { ...wp, isStopBy: false, connectToRoute: undefined };
      }
      return next;
    });
    setIsDirty(true);
  };

  const colorNames = presetColorNames();

  const setLegColor = (wpId: string, lineColor: [number, number, number] | undefined) => {
    updateWaypoint(wpId, { lineColor });
    setIsDirty(true);
  };

  const setPath = (wpId: string, customRoute: [number, number][]) => {
    updateWaypoint(wpId, { customRoute, routeMode: "draw" });
    setIsDirty(true);
  };

  const legMenu = (wp: Waypoint): MenuEntry[] => {
    const index = waypoints.findIndex((w) => w.id === wp.id);
    if (index === -1 || index === waypoints.length - 1) return [];
    const current = wp.routeMode || "driving";
    const pathEmpty = !wp.customRoute || wp.customRoute.length === 0;
    const drawnElsewhere = waypoints.filter(
      (w) => w.id !== wp.id && w.customRoute && w.customRoute.length > 0,
    );
    const previousPath = index > 0 ? waypoints[index - 1].customRoute : undefined;
    const viaCount = wp.viaPoints?.length ?? 0;

    return [
      ...modeOptions.map((option) => ({
        label: option.label,
        icon: option.icon,
        checked: current === option.id,
        onSelect: () => setLegMode(wp, option.id),
      })),
      separator,
      current === "draw" && {
        label: t`Edit path`,
        icon: Pencil,
        onSelect: () => startDrawing(wp.id),
      },
      current === "draw" &&
      pathEmpty &&
      drawnElsewhere.length > 0 && {
        label: t`Copy path from`,
        icon: Copy,
        submenu: drawnElsewhere.map((w) => ({
          label: w.name || t`Waypoint`,
          onSelect: () => setPath(wp.id, [...w.customRoute!]),
        })),
      },
      current === "draw" &&
      pathEmpty &&
      !!previousPath?.length && {
        label: t`Retrace previous path`,
        icon: CornerDownLeft,
        onSelect: () => setPath(wp.id, [...previousPath].reverse()),
      },
      VIA_MODES.includes(wp.routeMode) && {
        label: t`Adjust route`,
        icon: Route,
        onSelect: () => startAdjusting(wp.id),
      },
      separator,
      legColorable(wp) && {
        label: t`Line color`,
        icon: colorDot(wp.lineColor ? rgbToHex(wp.lineColor) : null),
        submenu: [
          {
            label: t`Route color`,
            checked: !wp.lineColor,
            onSelect: () => setLegColor(wp.id, undefined),
          },
          separator,
          ...PRESET_COLORS.map((hex, i) => ({
            label: colorNames[i],
            icon: colorDot(hex),
            checked: !!wp.lineColor && rgbToHex(wp.lineColor) === hex,
            onSelect: () => setLegColor(wp.id, hexToRgb(hex)),
          })),
        ],
      },
      viaCount > 0 && {
        label: t`Clear via points (${viaCount})`,
        icon: X,
        danger: true,
        onSelect: () => {
          updateWaypoint(wp.id, { viaPoints: [] });
          setIsDirty(true);
        },
      },
    ].filter(Boolean) as MenuEntry[];
  };

  const stopMenu = (wpId: string): MenuEntry[] => {
    const index = waypoints.findIndex((w) => w.id === wpId);
    const wp = waypoints[index];
    if (!wp) return [];
    const isLast = index === waypoints.length - 1;
    const currentType =
      index === 0 ? "start" : isLast && waypoints.length > 1 ? "end" : wp.isStopBy ? "stopby" : "normal";

    return [
      { type: "label", label: wp.name || t`Waypoint` },
      { label: t`Edit stop`, icon: Edit2, onSelect: () => setActiveWaypointId(wp.id) },
      {
        label: t`Show on map`,
        icon: LocateFixed,
        onSelect: () =>
          window.dispatchEvent(new CustomEvent("focus-waypoint", { detail: { wpId: wp.id } })),
      },
      separator,
      {
        label: t`Stop type`,
        icon: MapPinned,
        submenu: [
          { label: t`Start`, checked: currentType === "start", onSelect: () => setStopType(wp.id, "start") },
          { label: t`Stop`, checked: currentType === "normal", onSelect: () => setStopType(wp.id, "normal") },
          { label: t`Stop-by`, checked: currentType === "stopby", onSelect: () => setStopType(wp.id, "stopby") },
          { label: t`Destination`, checked: currentType === "end", onSelect: () => setStopType(wp.id, "end") },
        ],
      },
      wp.isStopBy && {
        label: t`On route`,
        icon: LinkIcon,
        checked: !!wp.connectToRoute,
        onSelect: () => {
          updateWaypoint(wp.id, { connectToRoute: !wp.connectToRoute });
          setIsDirty(true);
        },
      },
      !isLast && { label: t`Route to next stop`, icon: Route, submenu: legMenu(wp) },
      separator,
      { label: t`Add return stop`, icon: CornerDownLeft, onSelect: () => addReturnStop(wp.id) },
      {
        label: t`Duplicate`,
        icon: CopyPlus,
        onSelect: () => {
          const copy: Waypoint = {
            ...wp,
            id: Math.random().toString(36).substring(7),
            name: t`${wp.name} (copy)`,
            lat: wp.lat + 0.0005,
            lng: wp.lng + 0.0005,
          };
          setWaypoints((prev) => {
            const at = prev.findIndex((w) => w.id === wp.id);
            const next = [...prev];
            next.splice(at + 1, 0, copy);
            return next;
          });
          setActiveWaypointId(copy.id);
          setIsDirty(true);
        },
      },
      separator,
      {
        label: t`Delete stop`,
        icon: Trash2,
        danger: true,
        onSelect: () => {
          setWaypoints((prev) => prev.filter((w) => w.id !== wp.id));
          setActiveWaypointId(null);
          setIsDirty(true);
        },
      },
    ].filter(Boolean) as MenuEntry[];
  };

  const viaMenu = (wpId: string, viaIndex: number): MenuEntry[] => {
    const wp = waypoints.find((w) => w.id === wpId);
    const count = wp?.viaPoints?.length ?? 0;
    const removeAt = (i: number | "all") => {
      setWaypoints((prev) =>
        prev.map((w) =>
          w.id === wpId
            ? { ...w, viaPoints: i === "all" ? [] : (w.viaPoints || []).filter((_, j) => j !== i) }
            : w,
        ),
      );
      setIsDirty(true);
    };
    return [
      { type: "label", label: t`Via point ${viaIndex + 1} of ${count}` },
      { label: t`Adjust route`, icon: Route, onSelect: () => startAdjusting(wpId) },
      separator,
      { label: t`Remove via point`, icon: Trash2, danger: true, onSelect: () => removeAt(viaIndex) },
      count > 1 && {
        label: t`Remove all ${count} via points`,
        icon: X,
        danger: true,
        onSelect: () => removeAt("all"),
      },
    ].filter(Boolean) as MenuEntry[];
  };

  const mapMenu = (
    lat: number,
    lng: number,
    add: {
      stop: () => void;
      stopBy: () => void;
      start: () => void;
      end: () => void;
    },
  ): MenuEntry[] => [
      { label: t`Add stop here`, icon: MapPinPlus, onSelect: add.stop },
      { label: t`Add stop-by here`, icon: MapPinPlus, onSelect: add.stopBy },
      separator,
      { label: t`Add as start`, icon: MapPinned, onSelect: add.start },
      { label: t`Add as destination`, icon: Flag, onSelect: add.end },
      separator,
      {
        label: t`Copy coordinates`,
        icon: Copy,
        onSelect: () => void navigator.clipboard.writeText(`${lat.toFixed(6)}, ${lng.toFixed(6)}`),
      },
    ];

  return { stopMenu, legMenu, viaMenu, mapMenu };
}

function colorDot(hex: string | null) {
  return ({ className }: { className?: string }) =>
    createElement("span", {
      className: `${className ?? ""} inline-block rounded-full ring-1 ring-inset ring-black/15 dark:ring-white/20 ${
        hex ? "" : "bg-[conic-gradient(#ef4444,#f59e0b,#10b981,#3b82f6,#8b5cf6,#ef4444)]"
      }`,
      style: hex ? { backgroundColor: hex } : undefined,
    });
}
